import type { components } from "@zuula/shared"

import { ApiError, apiBaseUrl, authMode, request } from "@/lib/api"
import type { SubmissionValues } from "@/lib/submission"
import { accessToken } from "@/lib/supabase-auth"

// Real apps/api client for submissions (FR-SUBMIT-01…06, FR-DETECT-07): create one, then follow
// the pipeline over server-sent events, falling back to polling its status. Demo mode (no API)
// keeps lib/mock/submissions.ts's simulated flow, which is also where the Status page keeps the
// "what you submitted" preview: the API's status doesn't repeat the content.

type Schemas = components["schemas"]
export type SubmissionAccepted = Schemas["SubmissionAccepted"]
export type SubmissionStatus = Schemas["SubmissionStatusResponse"]
export type SubmissionStep = Schemas["SubmissionStepEvent"]

export function submissionsLive(): boolean {
  return authMode() !== "demo"
}

/** SubmissionInput fields for the active tab only (the form keeps every tab's values). */
export function inputOf(v: SubmissionValues): Record<string, string> {
  const input: Record<string, string> = { type: v.type, language: v.language }
  if (v.captchaToken) input.captchaToken = v.captchaToken
  if (v.type === "text") input.content = v.text.trim()
  if (v.type === "url") input.url = v.url.trim()
  if (v.type === "article") {
    input.content = v.body.trim()
    if (v.headline.trim()) input.headline = v.headline.trim()
    if (v.articleUrl.trim()) input.articleUrl = v.articleUrl.trim()
  }
  return input
}

/**
 * POST /submissions. Text, links and articles go as JSON; a media file as multipart over
 * XMLHttpRequest, the only browser API that reports upload progress. `idempotencyKey` makes a
 * retried request return the same submission instead of creating a second one.
 */
export async function createSubmission(
  values: SubmissionValues,
  {
    idempotencyKey,
    onUploadProgress,
  }: { idempotencyKey: string; onUploadProgress?: (percent: number) => void }
): Promise<SubmissionAccepted> {
  if (values.type !== "media" || !values.file) {
    return request<SubmissionAccepted>("/api/v1/submissions", {
      method: "POST",
      body: inputOf(values),
      headers: { "Idempotency-Key": idempotencyKey },
    })
  }

  const base = apiBaseUrl()
  if (base === null) throw new ApiError(0, "unconfigured", "NEXT_PUBLIC_API_URL is not set.")
  const form = new FormData()
  for (const [key, value] of Object.entries(inputOf(values))) form.append(key, value)
  form.append("file", values.file)
  const token = authMode() === "supabase" ? await accessToken() : null

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${base}/api/v1/submissions`)
    xhr.withCredentials = true
    xhr.setRequestHeader("Idempotency-Key", idempotencyKey)
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onUploadProgress?.(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onerror = () => reject(new ApiError(0, "network", "Couldn't reach the Zuula API."))
    xhr.onload = () => {
      let data: unknown
      try {
        data = JSON.parse(xhr.responseText)
      } catch {
        data = undefined
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data as SubmissionAccepted)
      const error = (data as Partial<Schemas["ErrorEnvelope"]> | undefined)?.error
      reject(
        new ApiError(
          xhr.status,
          error?.code ?? "server_error",
          error?.message ?? `Request failed (${xhr.status}).`
        )
      )
    }
    xhr.send(form)
  })
}

/** GET /submissions/{trackingId}: status, the steps so far and, once complete, the report. */
export function getSubmissionStatus(trackingId: string): Promise<SubmissionStatus> {
  return request<SubmissionStatus>(`/api/v1/submissions/${encodeURIComponent(trackingId)}`)
}

const POLL_MS = 2000

/**
 * Follows a submission until it completes or fails: `onStep` for each pipeline step, then
 * `onFinish` with the final status. Uses the API's event stream, and polls the status instead
 * if the stream can't be opened or drops. Returns a function that stops following.
 */
export function followSubmission(
  trackingId: string,
  {
    onStep,
    onFinish,
    onError,
  }: {
    onStep: (step: SubmissionStep) => void
    onFinish: (status: SubmissionStatus) => void
    onError: (error: unknown) => void
  }
): () => void {
  let stopped = false
  let poll: ReturnType<typeof setTimeout> | undefined
  let source: EventSource | undefined

  const finish = (status: SubmissionStatus) => {
    if (stopped) return
    stopped = true
    source?.close()
    onFinish(status)
  }

  const pollStatus = async () => {
    if (stopped) return
    try {
      const status = await getSubmissionStatus(trackingId)
      status.steps?.forEach((step) => onStep(step))
      if (status.status === "completed" || status.status === "failed") return finish(status)
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        stopped = true
        return onError(e)
      }
    }
    if (!stopped) poll = setTimeout(pollStatus, POLL_MS)
  }

  const base = apiBaseUrl()
  if (base === null || typeof EventSource === "undefined") {
    void pollStatus()
  } else {
    source = new EventSource(`${base}/api/v1/submissions/${encodeURIComponent(trackingId)}/events`)
    source.addEventListener("step", (e) => onStep(JSON.parse((e as MessageEvent).data)))
    for (const name of ["done", "failed"]) {
      source.addEventListener(name, (e) => finish(JSON.parse((e as MessageEvent).data)))
    }
    source.onerror = () => {
      // The stream ended early or never opened (a proxy, Redis down): poll instead.
      source?.close()
      source = undefined
      if (!stopped && poll === undefined) void pollStatus()
    }
  }

  return () => {
    stopped = true
    source?.close()
    if (poll !== undefined) clearTimeout(poll)
  }
}

"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { zodResolver } from "@hookform/resolvers/zod"
import { useForm, useWatch } from "react-hook-form"
import { toast } from "sonner"

import { useSession } from "@/components/providers/session-provider"
import { startNavigationProgress } from "@/components/shell/route-progress"
import { ApiError } from "@/lib/api"
import { newTrackingId, saveSubmission } from "@/lib/mock/submissions"
import { EMPTY_SUBMISSION, submissionSchema, type SubmissionValues } from "@/lib/submission"
import { createSubmission, submissionsLive } from "@/lib/submissions-api"

function previewOf(v: SubmissionValues) {
  switch (v.type) {
    case "text":
      return v.text.trim().slice(0, 200)
    case "url":
      return v.url.trim()
    case "media":
      return v.file?.name ?? ""
    case "article":
      return (v.headline.trim() || v.body.trim()).slice(0, 200)
  }
}

// A lone http(s) link, possibly with whitespace around it.
export function isLink(value: string) {
  return /^https?:\/\/\S+$/i.test(value.trim())
}

// Form state and submit flow shared by the full composer (/verify) and the quick one (Home):
// validate → POST /submissions (upload progress for media) → tracking ID → Status page. In
// demo mode (no API) the upload and tracking ID are simulated.
export function useSubmissionForm({ detectLinks = false }: { detectLinks?: boolean } = {}) {
  const router = useRouter()
  // FR-AUTH-07: anyone may submit; only a real account skips the CAPTCHA, never a role preview.
  const { source } = useSession()
  const signedIn = source === "account"
  const [uploadProgress, setUploadProgress] = React.useState<number | undefined>()

  const form = useForm<SubmissionValues>({
    resolver: zodResolver(submissionSchema),
    defaultValues: EMPTY_SUBMISSION,
    mode: "onSubmit",
    reValidateMode: "onChange",
  })
  const { control, handleSubmit, getValues, setValue, formState } = form
  const type = useWatch({ control, name: "type" })
  const text = useWatch({ control, name: "text" })
  const body = useWatch({ control, name: "body" })
  const submitting = formState.isSubmitting

  const onToken = React.useCallback(
    (token: string | null) => setValue("captchaToken", token),
    [setValue]
  )

  async function onSubmit(values: SubmissionValues) {
    if (!signedIn && !values.captchaToken) {
      toast.error("Please complete the human check first.")
      return
    }

    let trackingId: string
    if (submissionsLive()) {
      try {
        // One key per submit attempt: a retried request returns the same submission.
        const accepted = await createSubmission(values, {
          idempotencyKey: crypto.randomUUID(),
          onUploadProgress: values.type === "media" ? setUploadProgress : undefined,
        })
        trackingId = accepted.trackingId
      } catch (e) {
        setUploadProgress(undefined)
        toast.error(e instanceof ApiError ? e.message : "Couldn't submit. Please try again.")
        return
      }
    } else {
      // Demo mode (no API): a simulated upload and a locally made tracking ID.
      if (values.type === "media") {
        for (let p = 0; p <= 100; p += 10) {
          setUploadProgress(p)
          await new Promise((r) => setTimeout(r, 120))
        }
      } else {
        await new Promise((r) => setTimeout(r, 400))
      }
      trackingId = newTrackingId()
    }

    // Kept locally either way, for the Status page's "what you submitted" card.
    saveSubmission({
      trackingId,
      type: values.type,
      language: values.language,
      preview: previewOf(values),
      fileName: values.file?.name,
      submittedAt: new Date().toISOString(),
    })
    toast.success("Submitted for checking", { description: `Tracking ID ${trackingId}` })
    startNavigationProgress()
    router.push(`/submissions/${trackingId}`)
  }

  // With detectLinks, a text box holding nothing but a link is submitted as a link (the quick
  // composer has one box for both).
  function submit(e?: React.BaseSyntheticEvent) {
    if (detectLinks) {
      const { type: current, text: value } = getValues()
      if (current === "text" && isLink(value)) {
        setValue("type", "url")
        setValue("url", value.trim())
      }
    }
    return handleSubmit(onSubmit)(e)
  }

  // Ctrl/Cmd + Enter submits from any field.
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      void submit()
    }
  }

  return { form, control, type, text, body, submitting, uploadProgress, signedIn, onToken, submit, onKeyDown }
}

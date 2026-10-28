import type { components, operations } from "@zuula/shared"

import { demoAuthApi } from "@/lib/demo-auth"
import { accessToken, supabaseAuthApi } from "@/lib/supabase-auth"

// Thin client for apps/api (the core /api/v1 surface), typed from packages/shared's generated
// openapi.ts. The identity/session calls live here; lib/ratings-api.ts and lib/review-api.ts
// reuse request()/JsonBody below for the ratings and review surfaces (FR-RATE, FR-REVIEW).
// Admin and account settings still come from lib/mock until their turn.
//
// The session is the API's HttpOnly `zuula_session` cookie, so every call sends credentials
// and this code never sees the token. That only works when the API lists this site's origin in
// ZUULA_CORS_ORIGINS and the browser sees both on the same site: the cookie is SameSite=Lax.
// That holds for localhost:3000 → localhost:8000, for zuula.ug → api.zuula.ug, and for any
// host when this site proxies the API (NEXT_PUBLIC_API_URL=/, see next.config.ts).

type Schemas = components["schemas"]

export type UserProfile = Schemas["UserProfile"]
export type ApiSession = Schemas["Session"]
export type TwoFactorChallenge = Schemas["TwoFactorChallenge"]
export type ApiErrorCode = Schemas["ErrorEnvelope"]["error"]["code"]

export type JsonBody<Op extends keyof operations> = operations[Op] extends {
  requestBody: { content: { "application/json": infer B } }
}
  ? B
  : never

type SignUpAccepted = operations["signUp"]["responses"][202]["content"]["application/json"]

// Where apps/api lives. NEXT_PUBLIC_* is inlined at build time, so it must be read as this
// literal expression. "/" means this site's own origin: next.config.ts proxies /api/v1/* to
// ZUULA_API_ORIGIN (the way to deploy when the API isn't on a sibling subdomain). Returns ""
// then, so paths stay relative. Development falls back to the API's default local address; a
// production build without it configured refuses to send anything rather than guess.
export function apiBaseUrl(): string | null {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim()
  if (configured) return configured.replace(/\/+$/, "")
  return process.env.NODE_ENV === "production" ? null : "http://localhost:8000"
}

// "api": real sign-in against apps/api. "demo": the browser-only demo sign-in in
// lib/demo-auth.ts (any password, role from the address). "supabase": Supabase Auth
// (lib/supabase-auth.ts), with the API accepting its tokens; only when forced, never a default.
// NEXT_PUBLIC_AUTH_MODE forces any of them; unset, a build with an API address uses it and a
// build without one (the deployed site until the API is hosted) falls back to the demo instead
// of refusing to sign anyone in.
export type AuthMode = "api" | "demo" | "supabase"

export function authMode(): AuthMode {
  const forced = process.env.NEXT_PUBLIC_AUTH_MODE?.trim()
  if (forced === "api" || forced === "demo" || forced === "supabase") return forced
  return apiBaseUrl() === null ? "demo" : "api"
}

export class ApiError extends Error {
  /** HTTP status; 0 when the request never got a response. */
  readonly status: number
  /** The contract's error code, or "network" / "unconfigured" for failures before a response. */
  readonly code: ApiErrorCode | "network" | "unconfigured"
  readonly retryAfter?: number

  constructor(status: number, code: ApiError["code"], message: string, retryAfter?: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

export async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; headers?: Record<string, string> } = {}
): Promise<T> {
  const base = apiBaseUrl()
  if (base === null) throw new ApiError(0, "unconfigured", "NEXT_PUBLIC_API_URL is not set.")

  const headers: Record<string, string> = { ...init.headers }
  if (init.body !== undefined) headers["Content-Type"] = "application/json"
  // Supabase mode: the session is Supabase's, so its access token goes along as a bearer.
  const token = authMode() === "supabase" ? await accessToken() : null
  if (token) headers.Authorization = `Bearer ${token}`

  let res: Response
  try {
    res = await fetch(`${base}${path}`, {
      method: init.method ?? "GET",
      credentials: "include",
      cache: "no-store",
      headers: Object.keys(headers).length ? headers : undefined,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch {
    throw new ApiError(0, "network", "Couldn't reach the Zuula API.")
  }

  const text = await res.text()
  let data: unknown = undefined
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      // Not JSON (a proxy error page, say); handled below.
    }
  }

  if (!res.ok) {
    const error = (data as Partial<Schemas["ErrorEnvelope"]> | undefined)?.error
    throw new ApiError(
      res.status,
      error?.code ?? "server_error",
      error?.message ?? `Request failed (${res.status}).`,
      error?.retryAfter
    )
  }
  return data as T
}

export function isTwoFactorChallenge(r: ApiSession | TwoFactorChallenge): r is TwoFactorChallenge {
  return "challengeId" in r
}

const realAuthApi = {
  signUp: (body: JsonBody<"signUp">) =>
    request<SignUpAccepted>("/api/v1/auth/sign-up", { method: "POST", body }),

  // The sign-up it belongs to travels in the API's HttpOnly `zuula_signup` cookie.
  verifySignUp: (body: JsonBody<"verifySignUp">) =>
    request<ApiSession>("/api/v1/auth/sign-up/verify", { method: "POST", body }),

  signIn: (body: JsonBody<"signIn">) =>
    request<ApiSession | TwoFactorChallenge>("/api/v1/auth/sign-in", { method: "POST", body }),

  verifyTwoFactor: (body: JsonBody<"verifyTwoFactor">) =>
    request<ApiSession>("/api/v1/auth/two-factor/verify", { method: "POST", body }),

  resendTwoFactor: (body: JsonBody<"resendTwoFactor">) =>
    request<void>("/api/v1/auth/two-factor/resend", { method: "POST", body }),

  signOut: () => request<void>("/api/v1/auth/sign-out", { method: "POST" }),

  forgotPassword: (body: JsonBody<"forgotPassword">) =>
    request<void>("/api/v1/auth/forgot-password", { method: "POST", body }),

  resetPassword: (body: JsonBody<"resetPassword">) =>
    request<void>("/api/v1/auth/reset-password", { method: "POST", body }),

  /** The signed-in user, or null when the session cookie is missing, expired or revoked. */
  async me(): Promise<UserProfile | null> {
    try {
      return await request<UserProfile>("/api/v1/me")
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null
      throw e
    }
  },
}

// What the app calls. Resolved per call, so tests (and nothing else) can switch modes.
const AUTH_APIS: Record<AuthMode, typeof realAuthApi> = {
  api: realAuthApi,
  demo: demoAuthApi,
  supabase: supabaseAuthApi,
}

export const authApi: typeof realAuthApi = new Proxy(realAuthApi, {
  get: (_real, key: keyof typeof realAuthApi) => AUTH_APIS[authMode()][key],
})

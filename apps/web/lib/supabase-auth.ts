import {
  identifierKind,
  maskIdentifier,
  normalisePhone,
  safeNext,
} from "@/lib/auth"
import {
  ApiError,
  request,
  type ApiSession,
  type JsonBody,
  type TwoFactorChallenge,
  type UserProfile,
} from "@/lib/api"

// Supabase Auth sign-in (NEXT_PUBLIC_AUTH_MODE=supabase, Phase 1.2). Same calls and response
// shapes as the API's own auth in lib/api.ts, so the auth forms and the session provider don't
// know the difference. Supabase keeps the session (localStorage); request() sends its access
// token as `Authorization: Bearer`, and the API maps it to the Zuula account, creating a
// Public User on first sign-in (apps/api/app/core/supabase_auth.py, ZUULA_AUTH_PROVIDER=supabase).
//
// Needs, in the Supabase dashboard: "Confirm email" and "Secure email change" on; the
// "Confirm signup" and "Reset password" email templates showing {{ .Token }}, since the forms
// ask for the 6-digit code; an SMS provider for phone numbers.
// Not yet: the Expert/Admin second factor (FR-AUTH-05). Until Supabase MFA replaces it, this
// mode signs everyone in with a password alone, so it must not be switched on in production.
//
// lib/supabase.ts is imported lazily, so other auth modes never load supabase-js.

type SignUpAccepted = { maskedIdentifier: string }
type Credential = { email: string } | { phone: string }

const PENDING_KEY = "zuula.supabase-pending"
const NO_TWO_FACTOR =
  "Two-factor sign-in isn't available with Supabase sign-in yet."

async function auth() {
  return (await import("@/lib/supabase")).supabase.auth
}

/** Supabase wants E.164 phone numbers; the forms accept 07XX… and +2567XX… too. */
export function credential(identifier: string): Credential {
  const v = identifier.trim()
  if (identifierKind(v) === "phone") {
    return { phone: `+256${normalisePhone(v).replace(/^(?:\+?256|0)/, "")}` }
  }
  return { email: v.toLowerCase() }
}

function fail(error: { status?: number; message: string }): never {
  const status = error.status ?? 400
  const code =
    status === 429
      ? "rate_limited"
      : status === 401
        ? "unauthorized"
        : "bad_request"
  throw new ApiError(status, code, error.message)
}

function setPending(identifier: string | null) {
  try {
    if (identifier === null) sessionStorage.removeItem(PENDING_KEY)
    else sessionStorage.setItem(PENDING_KEY, identifier)
  } catch {
    // Storage unavailable: the code step will ask to start again.
  }
}

function pending(): string {
  let identifier: string | null = null
  try {
    identifier = sessionStorage.getItem(PENDING_KEY)
  } catch {
    // Same as missing.
  }
  if (!identifier)
    throw new ApiError(
      400,
      "bad_request",
      "That code has expired. Start again to get a new one."
    )
  return identifier
}

/** The Zuula account for the Supabase session just started. */
async function signedIn(): Promise<ApiSession> {
  const user = await supabaseAuthApi.me()
  if (!user) {
    await (await auth()).signOut()
    throw new ApiError(
      401,
      "unauthorized",
      "Signed in, but Zuula couldn't open your account."
    )
  }
  setPending(null)
  return { user }
}

/** OTP verification: email codes by type, phone codes are always "sms". */
async function verifyCode(
  identifier: string,
  token: string,
  emailType: "signup" | "recovery"
) {
  const c = credential(identifier)
  const { error } = await (
    await auth()
  ).verifyOtp(
    "email" in c
      ? { email: c.email, token, type: emailType }
      : { phone: c.phone, token, type: "sms" }
  )
  if (error) fail(error)
}

/** Supabase's OAuth round trip; it comes back to /auth/callback, which finishes the sign-in. */
export async function startOAuth(
  provider: "google" | "facebook",
  next?: string
) {
  const query = new URLSearchParams({ next: safeNext(next, "/") })
  const { error } = await (
    await auth()
  ).signInWithOAuth({
    provider,
    options: { redirectTo: `${window.location.origin}/auth/callback?${query}` },
  })
  if (error) fail(error)
}

/** The current Supabase access token, for request()'s Authorization header. */
export async function accessToken(): Promise<string | null> {
  const { data } = await (await auth()).getSession()
  return data.session?.access_token ?? null
}

export const supabaseAuthApi = {
  async signUp(body: JsonBody<"signUp">): Promise<SignUpAccepted> {
    const c = credential(body.identifier)
    const options = {
      data: { full_name: body.name.trim() },
      emailRedirectTo: `${window.location.origin}/auth/callback`,
    }
    const { error } = await (
      await auth()
    ).signUp(
      "email" in c
        ? { email: c.email, password: body.password, options }
        : { phone: c.phone, password: body.password, options }
    )
    if (error) fail(error)
    setPending(body.identifier)
    return { maskedIdentifier: maskIdentifier(body.identifier) }
  },

  async verifySignUp(body: JsonBody<"verifySignUp">): Promise<ApiSession> {
    await verifyCode(pending(), body.code, "signup")
    return signedIn()
  },

  async signIn(
    body: JsonBody<"signIn">
  ): Promise<ApiSession | TwoFactorChallenge> {
    const c = credential(body.identifier)
    const { error } = await (
      await auth()
    ).signInWithPassword(
      "email" in c
        ? { email: c.email, password: body.password }
        : { phone: c.phone, password: body.password }
    )
    if (error) fail(error)
    return signedIn()
  },

  async verifyTwoFactor(): Promise<ApiSession> {
    throw new ApiError(400, "bad_request", NO_TWO_FACTOR)
  },

  async resendTwoFactor(): Promise<void> {
    throw new ApiError(400, "bad_request", NO_TWO_FACTOR)
  },

  async signOut(): Promise<void> {
    setPending(null)
    const { error } = await (await auth()).signOut()
    if (error) fail(error)
  },

  /** Sends a reset code. Like the API, it doesn't say whether the account exists. */
  async forgotPassword(body: JsonBody<"forgotPassword">): Promise<void> {
    const c = credential(body.identifier)
    const a = await auth()
    const { error } =
      "email" in c
        ? await a.resetPasswordForEmail(c.email, {
            redirectTo: `${window.location.origin}/reset-password`,
          })
        : await a.signInWithOtp({
            phone: c.phone,
            options: { shouldCreateUser: false },
          })
    if (error?.status === 429) fail(error)
  },

  /** Checks the code, sets the new password, then signs out, as the API's reset does. */
  async resetPassword(body: JsonBody<"resetPassword">): Promise<void> {
    await verifyCode(body.identifier, body.code, "recovery")
    const a = await auth()
    const { error } = await a.updateUser({ password: body.password })
    await a.signOut()
    if (error) fail(error)
  },

  /** The signed-in Zuula account, or null without a Supabase session (or one the API refuses). */
  async me(): Promise<UserProfile | null> {
    if (!(await accessToken())) return null
    try {
      return await request<UserProfile>("/api/v1/me")
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null
      throw e
    }
  },
}

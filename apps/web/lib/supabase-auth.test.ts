// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError, authApi, authMode } from "@/lib/api"
import { credential } from "@/lib/supabase-auth"

// lib/supabase.ts is replaced with just the supabase.auth calls lib/supabase-auth.ts makes.
const auth = vi.hoisted(() => ({
  getSession: vi.fn(),
  signInWithPassword: vi.fn(),
  signOut: vi.fn(),
  verifyOtp: vi.fn(),
  signUp: vi.fn(),
}))
vi.mock("@/lib/supabase", () => ({ supabase: { auth } }))

const PROFILE = { id: "usr_1", name: "Amina Nakato", email: "amina@example.com", role: "public" }
const fetchMock = vi.fn<typeof fetch>()

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

function signedIn(token: string | null) {
  auth.getSession.mockResolvedValue({ data: { session: token ? { access_token: token } : null } })
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "supabase")
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://localhost:8000")
  vi.stubGlobal("fetch", fetchMock)
  fetchMock.mockReset()
  Object.values(auth).forEach((f) => f.mockReset())
  auth.signOut.mockResolvedValue({ error: null })
  sessionStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe("supabase auth mode", () => {
  it("is only used when NEXT_PUBLIC_AUTH_MODE asks for it", () => {
    expect(authMode()).toBe("supabase")
    vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "")
    expect(authMode()).toBe("api")
  })

  it("turns Ugandan numbers into E.164 for Supabase", () => {
    expect(credential("0772 123 456")).toEqual({ phone: "+256772123456" })
    expect(credential("+256772123456")).toEqual({ phone: "+256772123456" })
    expect(credential(" Amina@Example.com ")).toEqual({ email: "amina@example.com" })
  })

  it("signs in with Supabase, then sends its token to the API for the Zuula account", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null })
    signedIn("supabase-jwt")
    fetchMock.mockResolvedValueOnce(reply(200, { user: PROFILE }))

    await expect(authApi.signIn({ identifier: "amina@example.com", password: "x" })).resolves.toEqual({
      user: PROFILE,
    })
    expect(auth.signInWithPassword).toHaveBeenCalledWith({ email: "amina@example.com", password: "x" })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("http://localhost:8000/api/v1/auth/supabase/second-factor")
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer supabase-jwt")
  })

  it("hands Experts and Admins the API's code challenge, then verifies it with the same token", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null })
    signedIn("supabase-jwt")
    const challenge = { challengeId: "chl_1", maskedIdentifier: "da•••@example.com" }
    fetchMock.mockResolvedValueOnce(reply(200, challenge))

    await expect(authApi.signIn({ identifier: "david@example.com", password: "x" })).resolves.toEqual(challenge)
    expect(auth.signOut).not.toHaveBeenCalled()

    fetchMock.mockResolvedValueOnce(reply(200, { user: { ...PROFILE, role: "expert" } }))
    await expect(authApi.verifyTwoFactor({ challengeId: "chl_1", code: "123456" })).resolves.toMatchObject({
      user: { role: "expert" },
    })
    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toBe("http://localhost:8000/api/v1/auth/two-factor/verify")
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer supabase-jwt")
  })

  it("signs out of the API's second-factor record before Supabase", async () => {
    signedIn("supabase-jwt")
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
    await authApi.signOut()
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/auth/sign-out")
    expect(auth.signOut).toHaveBeenCalled()
  })

  it("surfaces Supabase's refusal as an ApiError", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: { status: 400, message: "Invalid login credentials" } })
    await expect(authApi.signIn({ identifier: "amina@example.com", password: "x" })).rejects.toMatchObject({
      status: 400,
      message: "Invalid login credentials",
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it("signs back out of Supabase when the API won't open the account", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null })
    signedIn("supabase-jwt")
    fetchMock.mockResolvedValueOnce(reply(401, { error: { code: "unauthorized", message: "Sign in required." } }))
    await expect(authApi.signIn({ identifier: "amina@example.com", password: "x" })).rejects.toBeInstanceOf(ApiError)
    expect(auth.signOut).toHaveBeenCalled()
  })

  it("verifies the sign-up code for the address the first step used", async () => {
    auth.signUp.mockResolvedValue({ error: null })
    auth.verifyOtp.mockResolvedValue({ error: null })
    signedIn("supabase-jwt")
    fetchMock.mockResolvedValueOnce(reply(200, { user: PROFILE }))

    await authApi.signUp({ name: "Amina", identifier: "0772123456", password: "x", consent: true })
    await expect(authApi.verifySignUp({ code: "123456" })).resolves.toEqual({ user: PROFILE })
    expect(auth.verifyOtp).toHaveBeenCalledWith({ phone: "+256772123456", token: "123456", type: "sms" })
  })

  it("reports an address that already has an account, instead of waiting for a code", async () => {
    // Supabase's response for an existing address: success, a user with no identities.
    auth.signUp.mockResolvedValue({ data: { user: { identities: [] } }, error: null })
    await expect(
      authApi.signUp({ name: "Amina", identifier: "amina@example.com", password: "x", consent: true })
    ).rejects.toMatchObject({ status: 409, code: "conflict" })
    await expect(authApi.verifySignUp({ code: "123456" })).rejects.toMatchObject({ code: "bad_request" })
  })

  it("is signed out, without calling the API, when there is no Supabase session", async () => {
    signedIn(null)
    await expect(authApi.me()).resolves.toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

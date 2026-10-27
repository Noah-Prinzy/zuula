// Supabase client for Zuula frontend.
//
// Phase 1.2 will move sign-in from lib/api.ts and lib/demo-auth.ts to Supabase Auth. Nothing
// imports this file yet. Supabase handles: email/password, OAuth (Google/Facebook), MFA,
// sessions, password reset. The OAuth redirect target /auth/callback doesn't exist yet.
//
// Usage:
//   import { supabase, signInWithGoogle, signOut, getCurrentUser } from '@/lib/supabase'
//
//   // Sign in with Google
//   await signInWithGoogle()
//
//   // Get current user
//   const user = await getCurrentUser()
//
//   // Sign out
//   await signOut()

import {
  createClient,
  type RealtimeChannel,
  type RealtimePostgresChangesPayload,
  type Session,
  type User,
} from "@supabase/supabase-js"

type RowChange = RealtimePostgresChangesPayload<Record<string, unknown>>

// ============================================================================
// CLIENT CONFIGURATION
// ============================================================================

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
// Supabase now uses "publishable" keys (sb_publishable_...) instead of legacy "anon" keys (eyJ...)
const supabasePublishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY

if (!supabaseUrl || !supabasePublishableKey) {
  console.warn(
    "Supabase not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY in .env.local"
  )
}

/**
 * Supabase client instance.
 * Uses the publishable key — safe for frontend use.
 * Row Level Security (RLS) policies protect the data.
 */
export const supabase = createClient(
  supabaseUrl || "https://placeholder.supabase.co",
  supabasePublishableKey || "placeholder-key",
  {
    auth: {
      // Persist session in localStorage (default) or cookies
      storage: typeof window !== "undefined" ? window.localStorage : undefined,
      // Auto-refresh tokens before they expire
      autoRefreshToken: true,
      // Persist session across browser sessions
      persistSession: true,
      // Detect session from URL (for OAuth callbacks)
      detectSessionInUrl: true,
    },
  }
)

// ============================================================================
// AUTH HELPERS
// ============================================================================

/**
 * Check if Supabase is properly configured.
 */
export function isSupabaseConfigured(): boolean {
  return !!(supabaseUrl && supabasePublishableKey)
}

/**
 * Sign up with email and password.
 */
export async function signUpWithEmail(
  email: string,
  password: string,
  metadata?: { name?: string }
) {
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: metadata,
    },
  })
  if (error) throw error
  return data
}

/**
 * Sign in with email and password.
 */
export async function signInWithEmail(email: string, password: string) {
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  })
  if (error) throw error
  return data
}

/**
 * Sign in with Google OAuth.
 */
export async function signInWithGoogle() {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: `${window.location.origin}/auth/callback`,
      queryParams: {
        access_type: "offline",
        prompt: "consent",
      },
    },
  })
  if (error) throw error
  return data
}

/**
 * Sign in with Facebook OAuth.
 */
export async function signInWithFacebook() {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "facebook",
    options: {
      redirectTo: `${window.location.origin}/auth/callback`,
    },
  })
  if (error) throw error
  return data
}

/**
 * Sign in with phone (SMS OTP).
 */
export async function signInWithPhone(phone: string) {
  const { data, error } = await supabase.auth.signInWithOtp({
    phone,
  })
  if (error) throw error
  return data
}

/**
 * Verify phone OTP.
 */
export async function verifyPhoneOTP(phone: string, token: string) {
  const { data, error } = await supabase.auth.verifyOtp({
    phone,
    token,
    type: "sms",
  })
  if (error) throw error
  return data
}

/**
 * Sign out the current user.
 */
export async function signOut() {
  const { error } = await supabase.auth.signOut()
  if (error) throw error
}

/**
 * Get the current session.
 */
export async function getSession(): Promise<Session | null> {
  const {
    data: { session },
    error,
  } = await supabase.auth.getSession()
  if (error) throw error
  return session
}

/**
 * Get the current user.
 */
export async function getCurrentUser(): Promise<User | null> {
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser()
  if (error) throw error
  return user
}

/**
 * Get the current access token (JWT) for API calls.
 * Pass this to FastAPI as: Authorization: Bearer <token>
 */
export async function getAccessToken(): Promise<string | null> {
  const session = await getSession()
  return session?.access_token || null
}

/**
 * Reset password (send reset email).
 */
export async function resetPassword(email: string) {
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/reset-password`,
  })
  if (error) throw error
}

/**
 * Update password (after reset).
 */
export async function updatePassword(newPassword: string) {
  const { error } = await supabase.auth.updateUser({
    password: newPassword,
  })
  if (error) throw error
}

// ============================================================================
// MFA (Multi-Factor Authentication)
// ============================================================================

/**
 * Enroll in TOTP MFA (authenticator app).
 */
export async function enrollMFA() {
  const { data, error } = await supabase.auth.mfa.enroll({
    factorType: "totp",
  })
  if (error) throw error
  return data
}

/**
 * Verify TOTP MFA enrollment.
 */
export async function verifyMFAEnrollment(factorId: string, code: string) {
  const { data, error } = await supabase.auth.mfa.challengeAndVerify({
    factorId,
    code,
  })
  if (error) throw error
  return data
}

/**
 * Challenge MFA (for sign-in with MFA).
 */
export async function challengeMFA(factorId: string) {
  const { data, error } = await supabase.auth.mfa.challenge({
    factorId,
  })
  if (error) throw error
  return data
}

/**
 * Verify MFA challenge (complete sign-in with MFA).
 */
export async function verifyMFAChallenge(
  factorId: string,
  challengeId: string,
  code: string
) {
  const { data, error } = await supabase.auth.mfa.verify({
    factorId,
    challengeId,
    code,
  })
  if (error) throw error
  return data
}

// ============================================================================
// REALTIME SUBSCRIPTIONS
// ============================================================================

/**
 * Subscribe to submission status changes.
 */
export function subscribeToSubmission(
  trackingId: string,
  callback: (payload: RowChange) => void
) {
  return supabase
    .channel(`submission:${trackingId}`)
    .on(
      "postgres_changes",
      {
        event: "UPDATE",
        schema: "public",
        table: "submissions",
        filter: `tracking_id=eq.${trackingId}`,
      },
      callback
    )
    .subscribe()
}

/**
 * Subscribe to user notifications.
 */
export function subscribeToNotifications(
  userId: string,
  callback: (payload: RowChange) => void
) {
  return supabase
    .channel(`notifications:${userId}`)
    .on(
      "postgres_changes",
      {
        event: "INSERT",
        schema: "public",
        table: "notifications",
        filter: `user_id=eq.${userId}`,
      },
      callback
    )
    .subscribe()
}

/**
 * Subscribe to fact-check updates (for live feed).
 */
export function subscribeToFactChecks(callback: (payload: RowChange) => void) {
  return supabase
    .channel("fact-checks")
    .on(
      "postgres_changes",
      {
        event: "*",
        schema: "public",
        table: "fact_check_reports",
      },
      callback
    )
    .subscribe()
}

/**
 * Unsubscribe from a channel.
 */
export async function unsubscribe(channel: RealtimeChannel) {
  await supabase.removeChannel(channel)
}

// ============================================================================
// AUTH STATE LISTENER
// ============================================================================

/**
 * Listen to auth state changes.
 * Useful for updating UI when user signs in/out.
 */
export function onAuthStateChange(
  callback: (event: string, session: Session | null) => void
) {
  return supabase.auth.onAuthStateChange(callback)
}

// ============================================================================
// EXPORTS
// ============================================================================

export type { User, Session }

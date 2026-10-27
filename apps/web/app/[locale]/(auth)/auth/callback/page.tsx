import { AuthCallback } from "@/components/auth/auth-callback"

// Supabase's error redirects use `error` (and `error_description`) in the query string.
type Props = { searchParams: Promise<{ next?: string; error?: string }> }

export default async function AuthCallbackPage({ searchParams }: Props) {
  const { next, error } = await searchParams
  return <AuthCallback next={next} error={error} />
}

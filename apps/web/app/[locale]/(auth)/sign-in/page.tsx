import { getTranslations } from "next-intl/server"

import { SignInForm } from "@/components/auth/sign-in-form"

export async function generateMetadata() {
  const t = await getTranslations("Auth.meta")
  return { title: t("signIn") }
}

type Props = { searchParams: Promise<{ next?: string; error?: string }> }

export default async function SignInPage({ searchParams }: Props) {
  const { next, error } = await searchParams
  return <SignInForm next={next} oauthError={error} />
}

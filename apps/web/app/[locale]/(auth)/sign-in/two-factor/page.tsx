import { getTranslations } from "next-intl/server"

import { TwoFactorForm } from "@/components/auth/two-factor-form"

export async function generateMetadata() {
  const t = await getTranslations("Auth.meta")
  return { title: t("twoFactor") }
}

type Props = { searchParams: Promise<{ challenge?: string }> }

export default async function TwoFactorPage({ searchParams }: Props) {
  const { challenge } = await searchParams
  return <TwoFactorForm challenge={challenge} />
}

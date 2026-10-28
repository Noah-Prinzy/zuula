import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"

import { CaseReview } from "@/components/review/case-review"
import { PageHeader } from "@/components/shell/page-header"

type Props = { params: Promise<{ id: string }> }

// Review case detail is signed-in, role-gated data fetched client-side (see CaseReview). No
// generateStaticParams, on purpose: with the [locale] layout's dynamicParams = false, any id
// not listed at build time would 404 — every real case the API creates. Without it, any id
// renders on request and CaseReview says when a case doesn't exist.
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const t = await getTranslations("Pages.caseReview")
  return { title: t("metaTitle", { id: (await params).id }) }
}

export default async function CasePage({ params }: Props) {
  const id = (await params).id
  const t = await getTranslations("Pages.caseReview")

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("title")} description={t("description")} />
      <CaseReview caseId={id} />
    </div>
  )
}

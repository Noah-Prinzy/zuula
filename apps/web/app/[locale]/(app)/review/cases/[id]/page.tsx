import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"

import { CaseReview } from "@/components/review/case-review"
import { PageHeader } from "@/components/shell/page-header"
import { SAMPLE_CASES } from "@/lib/mock/review"

type Props = { params: Promise<{ id: string }> }

// Review case detail is signed-in, role-gated data fetched client-side (see CaseReview's
// docstring) — this only pre-renders the sample cases' shells at build time; a real case id
// renders on demand (dynamicParams defaults to true; nothing here overrides it to false).
export function generateStaticParams() {
  return SAMPLE_CASES.map((c) => ({ id: c.id }))
}

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

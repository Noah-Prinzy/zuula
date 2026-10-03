import { Suspense } from "react"
import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"

import { PageHero, PageSheet } from "@/components/decor/page-sheet"
import { LibraryBrowser, LibraryBrowserFromUrl } from "@/components/library/library-browser"
import { factChecksApiConfigured, fetchAllReportsForLibrary } from "@/lib/fact-checks-api"
import { facets } from "@/lib/library"
import { SAMPLE_REPORTS } from "@/lib/mock/fact-checks"
import type { FactCheckReport } from "@/lib/types/fact-check"

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Library")
  return { title: t("metaTitle"), description: t("metaDescription") }
}

// Real data when the API is configured, the sample library otherwise or if the fetch fails —
// LibraryBrowser's own search/filter/sort/pagination (lib/library.ts) then runs over whichever
// set came back exactly as it does today, unchanged.
async function loadLibrary(): Promise<{
  reports: FactCheckReport[]
  categories: string[]
  languages: string[]
}> {
  if (factChecksApiConfigured()) {
    try {
      return await fetchAllReportsForLibrary()
    } catch {
      // Fall through to the sample library below.
    }
  }
  return { reports: SAMPLE_REPORTS, ...facets(SAMPLE_REPORTS) }
}

export default async function LibraryPage() {
  const { reports, categories, languages } = await loadLibrary()
  const t = await getTranslations("Library")

  return (
    <>
      <PageHero
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
      />
      <PageSheet>
      <div data-reveal className="flex page-container flex-col gap-6 py-10">
        {/* The fallback is the unfiltered library, so the static HTML has real results
            (not a skeleton) and most visitors see no change when the URL is read. */}
        <Suspense
          fallback={<LibraryBrowser reports={reports} categories={categories} languages={languages} />}
        >
          <LibraryBrowserFromUrl reports={reports} categories={categories} languages={languages} />
        </Suspense>
      </div>
      </PageSheet>
    </>
  )
}

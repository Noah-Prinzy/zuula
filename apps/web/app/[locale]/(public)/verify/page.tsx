import {
  RiArticleLine,
  RiFileTextLine,
  RiImageLine,
  RiLink,
  RiLockLine,
  RiWhatsappLine,
} from "@remixicon/react"

import type { Metadata } from "next"
import { getTranslations } from "next-intl/server"

import { PageHero, PageSheet } from "@/components/decor/page-sheet"
import { Leaderboard } from "@/components/home/leaderboard"
import { SubmissionComposer } from "@/components/submission/submission-composer"
import { TrackingLookup } from "@/components/submission/tracking-lookup"
import { factChecksApiConfigured, fetchHomeFeed } from "@/lib/fact-checks-api"
import { leaderboard } from "@/lib/library"
import { SAMPLE_REPORTS } from "@/lib/mock/fact-checks"

// Real data when the API is configured, the sample leaderboard otherwise or if the fetch
// fails (home-feed computes the same FR-RATE-10 ranking server-side as lib/library.ts's
// leaderboard() does locally).
async function loadLeaderboard() {
  if (factChecksApiConfigured()) {
    try {
      return (await fetchHomeFeed()).leaderboard
    } catch {
      // Fall through to the sample leaderboard below.
    }
  }
  return leaderboard(SAMPLE_REPORTS, 5)
}

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Verify")
  return { title: t("metaTitle"), description: t("metaDescription") }
}

// Text lives in Verify.steps.<key> and Verify.types.<key>.
const STEPS = ["submit", "analyse", "read"] as const

const TYPES = [
  { key: "text", icon: RiFileTextLine },
  { key: "link", icon: RiLink },
  { key: "media", icon: RiImageLine },
  { key: "article", icon: RiArticleLine },
] as const

export default async function VerifyPage() {
  const t = await getTranslations("Verify")
  const leaders = await loadLeaderboard()
  return (
    <>
    <PageHero title={t("title")} description={t("description")} />
    <PageSheet>
    <div className="page-container flex flex-col gap-8 py-10 max-md:pt-0">

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_26rem]">
        <SubmissionComposer className="enter [--d:2]" />

        <aside data-reveal="stagger" className="flex flex-col gap-6">
          <section aria-labelledby="how-it-works" className="hover-lift border bg-card p-4">
            <h2 id="how-it-works" className="mb-3 font-heading text-sm font-bold">
              {t("howTitle")}
            </h2>
            <ol className="flex flex-col gap-3">
              {STEPS.map((s, i) => (
                <li key={s} className="flex gap-3">
                  <span className="flex size-6 shrink-0 items-center justify-center bg-primary font-heading text-xs font-bold text-primary-foreground">
                    {i + 1}
                  </span>
                  <div>
                    <p className="text-sm font-medium">{t(`steps.${s}.title`)}</p>
                    <p className="text-sm text-muted-foreground">{t(`steps.${s}.body`)}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section aria-labelledby="what-to-submit" className="hover-lift border bg-card p-4">
            <h2 id="what-to-submit" className="mb-3 font-heading text-sm font-bold">
              {t("whatTitle")}
            </h2>
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
              {TYPES.map((type) => (
                <li key={type.key} className="flex gap-3">
                  <type.icon className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                  <div>
                    <p className="text-sm font-medium">{t(`types.${type.key}.title`)}</p>
                    <p className="text-sm text-muted-foreground">{t(`types.${type.key}.body`)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="track-title" className="hover-lift border bg-card p-4">
            <h2 id="track-title" className="mb-3 font-heading text-sm font-bold">
              {t("alreadyTitle")}
            </h2>
            <TrackingLookup />
          </section>

          <div className="flex flex-col gap-3 text-sm text-muted-foreground">
            <p className="flex gap-2">
              <RiWhatsappLine className="mt-0.5 size-4 shrink-0" aria-hidden />
              {t("whatsapp")}
            </p>
            <p className="flex gap-2">
              <RiLockLine className="mt-0.5 size-4 shrink-0" aria-hidden />
              {t("privacy")}
            </p>
          </div>
        </aside>
      </div>
    </div>
    </PageSheet>
    <Leaderboard leaders={leaders} />
    </>
  )
}

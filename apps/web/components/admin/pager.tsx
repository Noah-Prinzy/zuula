"use client"

import { useTranslations } from "next-intl"

import { Button } from "@/components/ui/button"

// Previous / next for a server-paged admin list. Renders nothing for a single page.
export function Pager({ page, total, perPage, onPage }: { page: number; total: number; perPage: number; onPage: (page: number) => void }) {
  const t = useTranslations("Admin.pager")
  const pages = Math.max(1, Math.ceil(total / perPage))
  if (pages <= 1) return null
  return (
    <nav aria-label={t("page", { page, pages })} className="flex items-center justify-end gap-2 text-sm">
      <span className="text-muted-foreground">{t("page", { page, pages })}</span>
      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t("previous")}
      </Button>
      <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {t("next")}
      </Button>
    </nav>
  )
}

"use client"

import * as React from "react"
import { RiAddLine, RiCheckboxCircleFill, RiErrorWarningFill, RiMore2Line, RiSearchLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { DataTable, SortableHeader, type AdminColumn } from "@/components/admin/data-table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useRelativeTime } from "@/hooks/use-relative-time"
import { adminApi, type Paged } from "@/lib/admin-api"
import {
  SAMPLE_SOURCES,
  SOURCE_TARGET,
  SOURCE_TYPE_LABELS,
  type SourceType,
  type TrustedSource,
} from "@/lib/mock/admin"
import { LOCALES } from "@/lib/locales"
import { cn } from "@/lib/utils"

import { useAdminData } from "./use-admin-data"

const DEMO: Paged<TrustedSource> = { data: SAMPLE_SOURCES, page: 1, perPage: 100, total: SAMPLE_SOURCES.length }

const EMPTY = { name: "", domain: "", type: "media" as SourceType, languages: "English", tier: "1" }

function SourceDialog({
  open,
  onOpenChange,
  initial,
  onSave,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  initial: TrustedSource | null
  onSave: (s: TrustedSource) => void | Promise<void>
}) {
  const [form, setForm] = React.useState(EMPTY)
  const [error, setError] = React.useState<string | null>(null)
  const t = useTranslations("Admin.sources")
  const tc = useTranslations("Common")

  // Reset when the dialog opens for a different source.
  const key = open ? (initial?.id ?? "new") : "closed"
  const [lastKey, setLastKey] = React.useState(key)
  if (key !== lastKey) {
    setLastKey(key)
    setError(null)
    setForm(
      initial
        ? { name: initial.name, domain: initial.domain, type: initial.type, languages: initial.languages.join(", "), tier: String(initial.tier) }
        : EMPTY
    )
  }

  function save(e: React.FormEvent) {
    e.preventDefault()
    const domain = form.domain.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "").toLowerCase()
    if (form.name.trim().length < 2) return setError(t("errors.name"))
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(domain)) return setError(t("errors.domain"))
    onSave({
      id: initial?.id ?? crypto.randomUUID(),
      name: form.name.trim(),
      domain,
      type: form.type,
      languages: form.languages.split(",").map((l) => l.trim()).filter(Boolean),
      tier: Number(form.tier) as 1 | 2 | 3,
      active: initial?.active ?? true,
      lastCrawled: initial?.lastCrawled ?? new Date().toISOString(),
      crawlOk: initial?.crawlOk ?? true,
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form noValidate onSubmit={save} className="flex flex-col gap-4">
          <DialogHeader>
            <DialogTitle>{initial ? t("editTitle", { name: initial.name }) : t("addTitle")}</DialogTitle>
            <DialogDescription>{t("dialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field className="sm:col-span-2">
              <FieldLabel htmlFor="src-name">{t("name")}</FieldLabel>
              <Input id="src-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="src-domain">{t("domain")}</FieldLabel>
              <Input id="src-domain" value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} placeholder="monitor.co.ug" />
            </Field>
            <Field>
              <FieldLabel htmlFor="src-type">{t("type")}</FieldLabel>
              <NativeSelect id="src-type" className="w-full" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as SourceType })}>
                {(Object.keys(SOURCE_TYPE_LABELS) as SourceType[]).map((type) => (
                  <NativeSelectOption key={type} value={type}>{t(`types.${type}`)}</NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="src-langs">{t("languages")}</FieldLabel>
              <Input id="src-langs" list="src-lang-list" value={form.languages} onChange={(e) => setForm({ ...form, languages: e.target.value })} />
              <datalist id="src-lang-list">
                {LOCALES.map((l) => <option key={l.code} value={l.label} />)}
              </datalist>
              <FieldDescription>{t("languagesHint")}</FieldDescription>
            </Field>
            <Field>
              <FieldLabel htmlFor="src-tier">{t("tier")}</FieldLabel>
              <NativeSelect id="src-tier" className="w-full" value={form.tier} onChange={(e) => setForm({ ...form, tier: e.target.value })}>
                <NativeSelectOption value="1">{t("tiers.1")}</NativeSelectOption>
                <NativeSelectOption value="2">{t("tiers.2")}</NativeSelectOption>
                <NativeSelectOption value="3">{t("tiers.3")}</NativeSelectOption>
              </NativeSelect>
            </Field>
          </div>
          {error && <FieldError>{error}</FieldError>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{tc("cancel")}</Button>
            <Button type="submit">{initial ? tc("saveChanges") : t("addSource")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// FR-ADMIN-03 / FR-DETECT-06: the trusted-source registry.
// FR-ADMIN-04: the trusted-source registry the verdict engine searches. Live, the list comes from
// the API (GET /admin/sources) and adding, editing and (de)activating are saved and audited
// there; it has no re-crawl action yet, so that one is demo-only.
export function SourceManager() {
  const { live, data } = useAdminData(() => adminApi.sources({ perPage: 100 }), DEMO, [])
  if (!data) return <Skeleton className="h-96 w-full" />
  return <Sources live={live} initial={data.data} />
}

function Sources({ live, initial }: { live: boolean; initial: TrustedSource[] }) {
  const [sources, setSources] = React.useState(initial)
  const errorMessage = useApiErrorMessage()

  // Saves a source (new when `isNew`); resolves with what to show, or null after an error.
  const persist = React.useCallback(async (s: TrustedSource, isNew: boolean): Promise<TrustedSource | null> => {
    if (!live) return s
    const input = { name: s.name, domain: s.domain, type: s.type, languages: s.languages, tier: s.tier, active: s.active }
    try {
      return await (isNew ? adminApi.addSource(input) : adminApi.updateSource(s.id, input))
    } catch (e) {
      toast.error(errorMessage(e))
      return null
    }
  }, [live, errorMessage])
  const show = React.useCallback(
    (s: TrustedSource) =>
      setSources((xs) => (xs.some((x) => x.id === s.id) ? xs.map((x) => (x.id === s.id ? s : x)) : [s, ...xs])),
    []
  )
  const [query, setQuery] = React.useState("")
  const [type, setType] = React.useState<SourceType | "">("")
  const [editing, setEditing] = React.useState<TrustedSource | null>(null)
  const [open, setOpen] = React.useState(false)
  const t = useTranslations("Admin.sources")
  const ta = useTranslations("Admin")
  const relativeTime = useRelativeTime()

  const active = sources.filter((s) => s.active).length
  const failing = sources.filter((s) => s.active && !s.crawlOk).length

  const rows = React.useMemo(() => {
    const q = query.trim().toLowerCase()
    return sources.filter((s) => (!q || `${s.name} ${s.domain}`.toLowerCase().includes(q)) && (!type || s.type === type))
  }, [sources, query, type])

  const columns = React.useMemo<AdminColumn<TrustedSource>[]>(
    () => [
      {
        id: "name",
        accessorFn: (s) => s.name,
        sortFn: "alphanumeric",
        header: ({ column }) => <SortableHeader column={column} label={t("columns.source")} />,
        meta: { label: t("columns.source") },
        cell: ({ row: { original: s } }) => (
          // Inactive sources are muted in colour, not faded with opacity, so they keep AA contrast.
          <div className="flex min-w-44 flex-col">
            <span className={cn("font-medium", !s.active && "text-muted-foreground")}>{s.name}</span>
            <span className="font-mono text-xs text-muted-foreground">{s.domain}</span>
          </div>
        ),
      },
      { id: "type", header: () => t("columns.type"), cell: ({ row: { original: s } }) => <Badge variant="outline">{t(`types.${s.type}`)}</Badge> },
      { id: "languages", header: () => t("columns.languages"), cell: ({ row: { original: s } }) => <span className="text-xs">{s.languages.join(", ")}</span> },
      {
        id: "tier",
        accessorFn: (s) => s.tier,
        sortFn: "basic",
        header: ({ column }) => <SortableHeader column={column} label={t("columns.tier")} />,
        meta: { label: t("columns.tier") },
        cell: ({ row: { original: s } }) => <span className="font-mono">{s.tier}</span>,
      },
      {
        id: "crawl",
        header: () => t("columns.crawl"),
        cell: ({ row: { original: s } }) =>
          !s.active ? (
            <span className="text-xs text-muted-foreground">{t("inactive")}</span>
          ) : (
            <span className={cn("inline-flex items-center gap-1 text-xs whitespace-nowrap", s.crawlOk ? "text-muted-foreground" : "text-verdict-false")}>
              {s.crawlOk ? <RiCheckboxCircleFill className="size-3.5 text-verdict-authentic" aria-label={t("ok")} /> : <RiErrorWarningFill className="size-3.5" aria-label={t("failing")} />}
              {s.crawlOk ? relativeTime(s.lastCrawled) : t("failing")}
            </span>
          ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">{t("columns.actions")}</span>,
        cell: ({ row: { original: s } }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t("actionsFor", { name: s.name })}>
                <RiMore2Line aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => { setEditing(s); setOpen(true) }}>{t("edit")}</DropdownMenuItem>
              {!live && (
                <DropdownMenuItem
                  onSelect={() => {
                    setSources((xs) => xs.map((x) => (x.id === s.id ? { ...x, lastCrawled: new Date().toISOString(), crawlOk: true } : x)))
                    toast.success(t("recrawlQueued", { name: s.name }))
                  }}
                >
                  {t("recrawl")}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                variant={s.active ? "destructive" : "default"}
                onSelect={async () => {
                  const saved = await persist({ ...s, active: !s.active }, false)
                  if (!saved) return
                  show(saved)
                  toast.success(s.active ? t("deactivated", { name: s.name }) : t("reactivated", { name: s.name }))
                }}
              >
                {s.active ? t("deactivate") : t("reactivate")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [t, relativeTime, live, persist, show]
  )

  return (
    <div className="flex flex-col gap-4">
      <div data-reveal="stagger" className="grid gap-3 md:grid-cols-3">
        <div className="flex flex-col gap-2 border bg-card p-4 md:col-span-2">
          <div className="flex items-baseline justify-between text-sm">
            <span>{t("active")}</span>
            <span className="font-mono tabular-nums">
              {t("activeCount", { active, target: SOURCE_TARGET })}
            </span>
          </div>
          <Progress value={(active / SOURCE_TARGET) * 100} aria-label={t("activeLabel", { active, target: SOURCE_TARGET })} />
          <span className="text-xs text-muted-foreground">{t("targetNote", { target: SOURCE_TARGET })}</span>
        </div>
        <div className={cn("flex flex-col gap-1 border p-4", failing ? "border-verdict-false/40 bg-verdict-false/5" : "bg-card")}>
          <span className="text-xs text-muted-foreground">{t("crawlsFailing")}</span>
          <span className={cn("font-heading text-3xl font-bold", failing && "text-verdict-false")}>{failing}</span>
        </div>
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <RiSearchLine className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchPlaceholder")} aria-label={t("searchLabel")} className="pl-9" />
        </div>
        <label htmlFor="src-filter" className="sr-only">{t("type")}</label>
        <NativeSelect id="src-filter" value={type} onChange={(e) => setType(e.target.value as SourceType | "")}>
          <NativeSelectOption value="">{t("allTypes")}</NativeSelectOption>
          {(Object.keys(SOURCE_TYPE_LABELS) as SourceType[]).map((type) => (
            <NativeSelectOption key={type} value={type}>{t(`types.${type}`)}</NativeSelectOption>
          ))}
        </NativeSelect>
        <Button onClick={() => { setEditing(null); setOpen(true) }}>
          <RiAddLine aria-hidden /> {t("addSource")}
        </Button>
      </div>

      <DataTable data={rows} columns={columns} getRowId={(s) => s.id} initialSorting={[{ id: "name", desc: false }]} />

      <SourceDialog
        open={open}
        onOpenChange={setOpen}
        initial={editing}
        onSave={async (s) => {
          const saved = await persist(s, !editing)
          if (!saved) return
          show(saved)
          toast.success(editing ? t("updated", { name: s.name }) : t("added", { name: s.name }), { description: ta("loggedInAudit") })
        }}
      />
    </div>
  )
}

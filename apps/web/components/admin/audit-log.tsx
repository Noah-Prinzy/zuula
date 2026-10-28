"use client"

import * as React from "react"
import { RiDownload2Line, RiSearchLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { DataTable, SortableHeader, type AdminColumn } from "@/components/admin/data-table"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { useFormat } from "@/lib/format"
import { Skeleton } from "@/components/ui/skeleton"
import { adminApi, type Paged } from "@/lib/admin-api"
import { AUDIT_ACTION_LABELS, SAMPLE_AUDIT, type AuditAction, type AuditEntry } from "@/lib/mock/admin"
import { initials } from "@/lib/utils"

import { Pager } from "./pager"
import { useAdminData } from "./use-admin-data"

const PER_PAGE = 100
const DEMO: Paged<AuditEntry> = { data: SAMPLE_AUDIT, page: 1, perPage: SAMPLE_AUDIT.length, total: SAMPLE_AUDIT.length }

function exportCsv(rows: AuditEntry[]) {
  const esc = (v: string) => `"${v.replace(/"/g, '""')}"`
  const csv = [
    "time,actor,role,action,target,detail,ip",
    ...rows.map((r) => [r.at, esc(r.actor), r.actorRole, r.action, esc(r.target), esc(r.detail), r.ip].join(",")),
  ].join("\n")
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }))
  const a = document.createElement("a")
  a.href = url
  a.download = "zuula-audit-log.csv"
  a.click()
  URL.revokeObjectURL(url)
}

// FR-ADMIN-07 / FR-REVIEW-03: append-only record of admin and expert actions.
export function AuditLog() {
  const [query, setQuery] = React.useState("")
  const [actor, setActor] = React.useState("")
  const [action, setAction] = React.useState<AuditAction | "">("")
  const [page, setPage] = React.useState(1)
  // FR-ADMIN-07: live, the API filters by action and pages newest first (GET /admin/audit-log);
  // the text search and actor filter narrow the loaded page.
  const { live, data } = useAdminData(
    () => adminApi.auditLog({ action: action || undefined, page, perPage: PER_PAGE }),
    DEMO,
    [action, page]
  )
  const entries = React.useMemo(() => (data?.data ?? []) as AuditEntry[], [data])
  const t = useTranslations("Admin.audit")
  const tRoles = useTranslations("Roles")
  const f = useFormat()
  // Action ids contain a dot ("verdict.override"), which next-intl reads as a nested path.
  const actionLabel = React.useCallback((a: AuditAction) => t(`actions.${a}`), [t])

  const actors = [...new Set(entries.map((a) => a.actor))].sort()
  const q = query.trim().toLowerCase()
  const rows = entries.filter(
    (e) =>
      (!q || `${e.target} ${e.detail}`.toLowerCase().includes(q)) &&
      (!actor || e.actor === actor) &&
      (!action || e.action === action)
  )

  const columns = React.useMemo<AdminColumn<AuditEntry>[]>(
    () => [
      {
        id: "at",
        accessorFn: (e) => e.at,
        sortFn: "alphanumeric",
        header: ({ column }) => <SortableHeader column={column} label={t("columns.time")} />,
        meta: { label: t("columns.time") },
        cell: ({ row: { original: e } }) => (
          <time dateTime={e.at} className="font-mono text-xs whitespace-nowrap">
            {f.dateTime(e.at)}
          </time>
        ),
      },
      {
        id: "actor",
        header: () => t("columns.actor"),
        cell: ({ row: { original: e } }) => (
          <div className="flex items-center gap-2 whitespace-nowrap">
            <Avatar className="size-6">
              <AvatarFallback className="text-[10px]">{initials(e.actor)}</AvatarFallback>
            </Avatar>
            <div className="flex flex-col">
              <span className="text-sm">{e.actor}</span>
              <span className="text-[11px] text-muted-foreground">{tRoles(e.actorRole)}</span>
            </div>
          </div>
        ),
      },
      {
        id: "action",
        header: () => t("columns.action"),
        cell: ({ row: { original: e } }) => <Badge variant="outline" className="whitespace-nowrap">{actionLabel(e.action)}</Badge>,
      },
      {
        id: "target",
        header: () => t("columns.target"),
        cell: ({ row: { original: e } }) => (
          <div className="flex min-w-64 flex-col">
            <span className="text-sm font-medium">{e.target}</span>
            <span className="text-xs text-muted-foreground">{e.detail}</span>
          </div>
        ),
      },
      {
        id: "ip",
        header: () => t("columns.ip"),
        cell: ({ row: { original: e } }) => <span className="font-mono text-xs text-muted-foreground">{e.ip}</span>,
      },
    ],
    [t, tRoles, f, actionLabel]
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <RiSearchLine className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchPlaceholder")} aria-label={t("searchLabel")} className="pl-9" />
        </div>
        <label htmlFor="audit-actor" className="sr-only">{t("actor")}</label>
        <NativeSelect id="audit-actor" value={actor} onChange={(e) => setActor(e.target.value)}>
          <NativeSelectOption value="">{t("everyone")}</NativeSelectOption>
          {actors.map((a) => <NativeSelectOption key={a} value={a}>{a}</NativeSelectOption>)}
        </NativeSelect>
        <label htmlFor="audit-action" className="sr-only">{t("action")}</label>
        <NativeSelect
          id="audit-action"
          value={action}
          onChange={(e) => {
            setAction(e.target.value as AuditAction | "")
            setPage(1)
          }}
        >
          <NativeSelectOption value="">{t("allActions")}</NativeSelectOption>
          {(Object.keys(AUDIT_ACTION_LABELS) as AuditAction[]).map((a) => (
            <NativeSelectOption key={a} value={a}>{actionLabel(a)}</NativeSelectOption>
          ))}
        </NativeSelect>
        <Button
          variant="outline"
          onClick={() => {
            exportCsv(rows)
            toast.success(t("exported", { count: rows.length }))
          }}
        >
          <RiDownload2Line aria-hidden /> {t("exportCsv")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {t("summary", { count: rows.length })}
      </p>
      {data ? (
        <DataTable data={rows} columns={columns} getRowId={(e) => e.id} initialSorting={[{ id: "at", desc: true }]} emptyTitle={t("emptyTitle")} />
      ) : (
        <Skeleton className="h-64 w-full" />
      )}
      {live && data && <Pager page={page} total={data.total} perPage={PER_PAGE} onPage={setPage} />}
    </div>
  )
}

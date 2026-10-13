"use client"

import * as React from "react"
import Link from "next/link"
import {
  createSortedRowModel,
  flexRender,
  rowSortingFeature,
  sortFn_basic,
  tableFeatures,
  useTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table"
import {
  RiArrowDownSLine,
  RiArrowUpDownLine,
  RiArrowUpSLine,
  RiSearchLine,
  RiUserAddLine,
} from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { TableCards } from "@/components/admin/data-table"
import { CommunityBadge } from "@/components/community/community-status"
import { useSession } from "@/components/providers/session-provider"
import { ReasonBadge, SlaBadge } from "@/components/review/review-badges"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { VerdictBadge } from "@/components/verdict/verdict-badge"
import { communityScore } from "@/lib/community"
import { fetchFullReport } from "@/lib/fact-checks-api"
import { useIsMobile } from "@/hooks/use-mobile"
import { getSampleReport, SAMPLE_REPORTS } from "@/lib/mock/fact-checks"
import { REASON_META, SAMPLE_CASES, type ReviewReason } from "@/lib/mock/review"
import {
  assignCase,
  dueAtFor,
  getQueue,
  hoursLeftFor,
  reviewApiConfigured,
  type ReviewCase,
} from "@/lib/review-api"
import type { FactCheckReport } from "@/lib/types/fact-check"

type Row = ReviewCase & {
  report: FactCheckReport
  ccs: number | null
  ratings: number
  hoursLeft: number
}

type Scope = "all" | "mine" | "unassigned"

// TanStack Table v9: features and row models are declared once, outside the component.
const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { basic: sortFn_basic },
})

function SortHeader({
  label,
  dir,
  onClick,
}: {
  label: string
  dir: false | "asc" | "desc"
  onClick: () => void
}) {
  const Icon =
    dir === "asc"
      ? RiArrowUpSLine
      : dir === "desc"
        ? RiArrowDownSLine
        : RiArrowUpDownLine
  return (
    <button
      type="button"
      onClick={onClick}
      className="press -ml-1 inline-flex items-center gap-1 px-1 [--press-scale:0.94] hover:text-foreground"
    >
      {label}
      <Icon className="size-3.5" aria-hidden />
    </button>
  )
}

function reportsById(reports: FactCheckReport[]): Map<string, FactCheckReport> {
  return new Map(reports.map((r) => [r.id, r]))
}

// FR-REVIEW-01 / 06: flagged verdicts awaiting expert review, most urgent first. Real API when
// configured (the queue plus every report, joined client-side — see reportsById above), the
// sample cases otherwise. Role-gated data, so (like review-history.tsx) this is fetched
// entirely client-side; there's no server-rendered fallback.
export function ReviewQueue() {
  const { user } = useSession()
  const [cases, setCases] = React.useState<ReviewCase[]>(SAMPLE_CASES)
  const [reports, setReports] = React.useState<Map<string, FactCheckReport>>(
    () => reportsById(SAMPLE_REPORTS)
  )
  const [query, setQuery] = React.useState("")
  const [reason, setReason] = React.useState<ReviewReason | "">("")
  const [scope, setScope] = React.useState<Scope>("all")
  const [sorting, setSorting] = React.useState<SortingState>([
    { id: "sla", desc: false },
  ])
  const t = useTranslations("Review.queue")
  const tr = useTranslations("Review.reasons")
  const tReview = useTranslations("Review")
  const isMobile = useIsMobile()

  React.useEffect(() => {
    if (!reviewApiConfigured()) return
    let cancelled = false
    getQueue({ perPage: 100 })
      .then(async (queue) => {
        if (cancelled) return
        setCases(queue.data)
        // Not fetchAllReportsForLibrary(): that's the public listing, which excludes
        // suspended reports (app/services/reports.py's LISTED) — exactly the kind of report a
        // review case is often open about. Fetch each case's report directly instead (GET
        // /fact-checks/{id} always serves it, suspended or not); a queue is small enough that
        // this isn't a real N+1 concern.
        const fetched = await Promise.all(
          queue.data.map((c) => fetchFullReport(c.reportId).catch(() => null))
        )
        if (cancelled) return
        setReports(
          reportsById(fetched.filter((r): r is FactCheckReport => r !== null))
        )
      })
      .catch(() => {
        // Keep the sample cases already in state.
      })
    return () => {
      cancelled = true
    }
  }, [])

  const assign = React.useCallback(
    async (id: string) => {
      if (!user) return
      if (reviewApiConfigured()) {
        try {
          const updated = await assignCase(id)
          setCases((cs) => cs.map((c) => (c.id === id ? updated : c)))
          toast.success(t("assigned"))
        } catch {
          toast.error(t("assignFailed"))
        }
        return
      }
      setCases((cs) =>
        cs.map((c) => (c.id === id ? { ...c, assignee: user.name } : c))
      )
      toast.success(t("assigned"))
    },
    [user, t]
  )

  const rows = React.useMemo<Row[]>(() => {
    const q = query.trim().toLowerCase()
    return cases
      .map((c) => {
        const report =
          reports.get(c.reportId) ??
          (reviewApiConfigured() ? undefined : getSampleReport(c.reportId))
        if (!report) return null
        const score = communityScore(report.community)
        return {
          ...c,
          report,
          ccs: score.ccs,
          ratings: score.total,
          hoursLeft: hoursLeftFor(dueAtFor(c)),
        }
      })
      .filter((r): r is Row => r !== null)
      .filter(
        (r) =>
          !q ||
          `${r.report.title} ${r.id} ${r.report.category}`
            .toLowerCase()
            .includes(q)
      )
      .filter((r) => !reason || r.reason === reason)
      .filter(
        (r) =>
          scope === "all" ||
          (scope === "mine" ? r.assignee === user?.name : r.assignee === null)
      )
  }, [cases, reports, query, reason, scope, user])

  const columns = React.useMemo<ColumnDef<typeof features, Row>[]>(
    () => [
      {
        id: "content",
        header: () => t("columns.content"),
        cell: ({ row: { original: r } }) => (
          <div className="flex min-w-64 flex-col gap-1">
            <Link
              href={`/review/cases/${r.id}`}
              className="font-medium hover:text-primary"
            >
              {r.report.title}
            </Link>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono text-xs text-muted-foreground">
                {r.id}
              </span>
              <ReasonBadge reason={r.reason} reports={r.reports} />
              {r.priority === "high" && (
                <Badge variant="destructive">{tReview("highPriority")}</Badge>
              )}
            </div>
          </div>
        ),
      },
      {
        id: "verdict",
        header: () => t("columns.verdict"),
        cell: ({ row: { original: r } }) => (
          <VerdictBadge verdict={r.report.verdict} size="sm" />
        ),
      },
      {
        id: "ccs",
        accessorFn: (r) => r.ccs ?? -1,
        sortFn: "basic",
        header: ({ column }) => (
          <SortHeader
            label={t("columns.ccs")}
            dir={column.getIsSorted()}
            onClick={() => column.toggleSorting()}
          />
        ),
        meta: { label: t("columns.ccs") },
        cell: ({ row: { original: r } }) => (
          <div className="flex flex-col gap-1">
            <span className="font-mono tabular-nums">
              {r.ccs === null ? "—" : `${r.ccs}%`}
            </span>
            <span className="text-xs text-muted-foreground">
              {t("ratings", { count: r.ratings })}
            </span>
            <CommunityBadge
              status={communityScore(r.report.community).status}
            />
          </div>
        ),
      },
      {
        id: "sla",
        accessorFn: (r) => r.hoursLeft,
        sortFn: "basic",
        header: ({ column }) => (
          <SortHeader
            label={t("columns.sla")}
            dir={column.getIsSorted()}
            onClick={() => column.toggleSorting()}
          />
        ),
        meta: { label: t("columns.sla") },
        cell: ({ row: { original: r } }) => <SlaBadge dueAt={dueAtFor(r)} />,
      },
      {
        id: "assignee",
        header: () => t("columns.assignee"),
        cell: ({ row: { original: r } }) =>
          r.assignee ? (
            <span className="text-sm whitespace-nowrap">
              {r.assignee === user?.name ? t("you") : r.assignee}
            </span>
          ) : (
            <Button variant="ghost" size="xs" onClick={() => assign(r.id)}>
              <RiUserAddLine aria-hidden /> {t("assignToMe")}
            </Button>
          ),
      },
      {
        id: "action",
        header: () => <span className="sr-only">{t("columns.action")}</span>,
        cell: ({ row: { original: r } }) => (
          <Button size="sm" asChild>
            <Link href={`/review/cases/${r.id}`}>{t("review")}</Link>
          </Button>
        ),
      },
    ],
    [assign, user, t, tReview]
  )

  const table = useTable({
    features,
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <RiSearchLine
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchLabel")}
            className="pl-9"
          />
        </div>
        <label htmlFor="queue-reason" className="sr-only">
          {t("reason")}
        </label>
        <NativeSelect
          id="queue-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value as ReviewReason | "")}
        >
          <NativeSelectOption value="">{t("allReasons")}</NativeSelectOption>
          {(Object.keys(REASON_META) as ReviewReason[]).map((r) => (
            <NativeSelectOption key={r} value={r}>
              {tr(`${r}.label`)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={scope}
          onValueChange={(v) => v && setScope(v as Scope)}
          aria-label={t("scopeLabel")}
        >
          <ToggleGroupItem value="all">{t("scopes.all")}</ToggleGroupItem>
          <ToggleGroupItem value="mine">{t("scopes.mine")}</ToggleGroupItem>
          <ToggleGroupItem value="unassigned">
            {t("scopes.unassigned")}
          </ToggleGroupItem>
        </ToggleGroup>
      </div>

      <p className="text-sm text-muted-foreground" aria-live="polite">
        {t("summary", {
          count: rows.length,
          sort: sorting[0]?.id === "ccs" ? "ccs" : "sla",
        })}
      </p>

      {rows.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{t("emptyTitle")}</EmptyTitle>
            <EmptyDescription>{t("emptyBody")}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : isMobile ? (
        <TableCards
          table={table}
          rowClassName={(r) =>
            r.hoursLeft < 0 ? "bg-verdict-false/[0.04]" : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto border bg-card">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((h) => (
                    <TableHead
                      key={h.id}
                      aria-sort={
                        h.column.getIsSorted() === "asc"
                          ? "ascending"
                          : h.column.getIsSorted() === "desc"
                            ? "descending"
                            : undefined
                      }
                    >
                      {h.isPlaceholder
                        ? null
                        : flexRender(h.column.columnDef.header, h.getContext())}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className={
                    row.original.hoursLeft < 0
                      ? "bg-verdict-false/[0.04]"
                      : undefined
                  }
                >
                  {row.getAllCells().map((cell) => (
                    <TableCell key={cell.id} className="align-top">
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

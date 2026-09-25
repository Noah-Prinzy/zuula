"use client"

import * as React from "react"
import {
  createSortedRowModel,
  flexRender,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_datetime,
  tableFeatures,
  useTable,
  type CellData,
  type Column,
  type ColumnDef,
  type RowData,
  type SortingState,
  type Table as TableInstance,
  type TableFeatures,
} from "@tanstack/react-table"
import { RiArrowDownSLine, RiArrowUpDownLine, RiArrowUpSLine } from "@remixicon/react"
import { useTranslations } from "next-intl"

import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useIsMobile } from "@/hooks/use-mobile"
import { cn } from "@/lib/utils"

declare module "@tanstack/react-table" {
  // Plain-text column name, for columns whose header is a component (a sort button, or a
  // screen-reader-only label). The phone card layout labels each value with it; a column
  // with neither a string header nor a label (e.g. row actions) goes unlabelled.
  // Type parameters must match the library's declaration for the interfaces to merge.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<in out TFeatures extends TableFeatures, in out TData extends RowData, TValue extends CellData = CellData> {
    label?: string
  }
}

// Shared sortable table for the admin pages (TanStack Table v9).
export const adminTableFeatures = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { basic: sortFn_basic, alphanumeric: sortFn_alphanumeric, datetime: sortFn_datetime },
})

export type AdminColumn<T extends RowData> = ColumnDef<typeof adminTableFeatures, T>

export function SortableHeader<T extends RowData>({ column, label }: { column: Column<typeof adminTableFeatures, T, unknown>; label: string }) {
  const dir = column.getIsSorted()
  const Icon = dir === "asc" ? RiArrowUpSLine : dir === "desc" ? RiArrowDownSLine : RiArrowUpDownLine
  return (
    <button type="button" onClick={() => column.toggleSorting()} className="press -ml-1 inline-flex items-center gap-1 px-1 [--press-scale:0.94] hover:text-foreground">
      {label}
      <Icon className="size-3.5" aria-hidden />
    </button>
  )
}

export function DataTable<T extends RowData>({
  data,
  columns,
  initialSorting = [],
  rowClassName,
  emptyTitle,
  emptyDescription,
  getRowId,
}: {
  data: T[]
  columns: AdminColumn<T>[]
  initialSorting?: SortingState
  rowClassName?: (row: T) => string | undefined
  emptyTitle?: string
  emptyDescription?: string
  getRowId?: (row: T) => string
}) {
  const [sorting, setSorting] = React.useState<SortingState>(initialSorting)
  const t = useTranslations("Admin.table")
  const isMobile = useIsMobile()
  const table = useTable({
    features: adminTableFeatures,
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getRowId: getRowId ? (row) => getRowId(row) : undefined,
  })

  if (data.length === 0) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>{emptyTitle ?? t("emptyTitle")}</EmptyTitle>
          <EmptyDescription>{emptyDescription ?? t("emptyBody")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  if (isMobile) return <TableCards table={table} rowClassName={rowClassName} />

  return (
    <div className="overflow-x-auto border bg-card">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id}>
              {hg.headers.map((h) => {
                const s = h.column.getIsSorted()
                return (
                  <TableHead key={h.id} aria-sort={s === "asc" ? "ascending" : s === "desc" ? "descending" : undefined}>
                    {h.isPlaceholder ? null : flexRender(h.column.columnDef.header, h.getContext())}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id} className={rowClassName?.(row.original)}>
              {row.getAllCells().map((cell) => (
                <TableCell key={cell.id} className="align-top">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function columnLabel<TFeatures extends TableFeatures, TData extends RowData>(column: Column<TFeatures, TData, unknown>) {
  const { header, meta } = column.columnDef as { header?: unknown; meta?: { label?: string } }
  return typeof header === "string" ? header : (meta?.label ?? null)
}

// Phones: each row becomes a card instead of a table row that scrolls sideways out of view.
// The first column is the card's heading, labelled columns follow as label/value pairs, and
// unlabelled ones (row actions) sit in a footer. Column-header sort buttons become a select.
export function TableCards<TFeatures extends TableFeatures, TData extends RowData>({
  table,
  rowClassName,
}: {
  table: TableInstance<TFeatures, TData>
  rowClassName?: (row: TData) => string | undefined
}) {
  const t = table as unknown as TableInstance<typeof adminTableFeatures, TData>
  const sortable = t.getAllLeafColumns().filter((c) => c.getCanSort())
  const [current] = t.store.state.sorting ?? []
  const sortId = React.useId()
  const sortValue = current ? `${current.id}:${current.desc ? "desc" : "asc"}` : ""

  return (
    <div className="flex flex-col gap-3">
      {sortable.length > 0 && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <label htmlFor={sortId} className="shrink-0">
            Sort by
          </label>
          <NativeSelect
            id={sortId}
            size="sm"
            value={sortValue}
            onChange={(e) => {
              const [id, dir] = e.target.value.split(":")
              t.setSorting(id ? [{ id, desc: dir === "desc" }] : [])
            }}
          >
            {!current && <NativeSelectOption value="">Default order</NativeSelectOption>}
            {sortable.flatMap((c) => {
              const label = columnLabel(c) ?? c.id
              return [
                <NativeSelectOption key={`${c.id}:asc`} value={`${c.id}:asc`}>
                  {label} ↑
                </NativeSelectOption>,
                <NativeSelectOption key={`${c.id}:desc`} value={`${c.id}:desc`}>
                  {label} ↓
                </NativeSelectOption>,
              ]
            })}
          </NativeSelect>
        </div>
      )}
      <ul className="flex flex-col gap-2">
        {t.getRowModel().rows.map((row) => {
          const [first, ...rest] = row.getAllCells()
          const labelled = rest.filter((c) => columnLabel(c.column) !== null)
          const actions = rest.filter((c) => columnLabel(c.column) === null)
          return (
            <li key={row.id} className={cn("flex flex-col gap-3 border bg-card p-3 text-xs", rowClassName?.(row.original))}>
              {first && <div className="min-w-0 text-sm [&_*]:min-w-0">{flexRender(first.column.columnDef.cell, first.getContext())}</div>}
              {labelled.length > 0 && (
                <dl className="grid grid-cols-[minmax(5rem,auto)_1fr] items-start gap-x-4 gap-y-2">
                  {labelled.map((cell) => (
                    <React.Fragment key={cell.id}>
                      <dt className="pt-0.5 text-muted-foreground">{columnLabel(cell.column)}</dt>
                      <dd className="min-w-0">{flexRender(cell.column.columnDef.cell, cell.getContext())}</dd>
                    </React.Fragment>
                  ))}
                </dl>
              )}
              {actions.length > 0 && (
                <div className="-mx-3 -mb-3 flex flex-wrap items-center justify-end gap-2 border-t px-3 py-2">
                  {actions.map((cell) => (
                    <React.Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</React.Fragment>
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

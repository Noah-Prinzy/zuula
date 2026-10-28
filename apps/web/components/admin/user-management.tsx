"use client"

import * as React from "react"
import { RiMore2Line, RiSearchLine } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { DataTable, SortableHeader, type AdminColumn } from "@/components/admin/data-table"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Textarea } from "@/components/ui/textarea"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { adminApi, type UsersPage } from "@/lib/admin-api"
import { SAMPLE_USERS, type AdminUser, type UserStatus } from "@/lib/mock/admin"
import { ROLES, type Role } from "@/lib/roles"
import { useFormat } from "@/lib/format"
import { cn, initials } from "@/lib/utils"

import { Pager } from "./pager"
import { useAdminData } from "./use-admin-data"

const PER_PAGE = 50
const countStatus = (users: AdminUser[], s: UserStatus) => users.filter((u) => u.status === s).length
const DEMO: UsersPage = {
  data: SAMPLE_USERS,
  page: 1,
  perPage: SAMPLE_USERS.length,
  total: SAMPLE_USERS.length,
  counts: { pending: countStatus(SAMPLE_USERS, "pending"), suspended: countStatus(SAMPLE_USERS, "suspended") },
}

// Keeps the platform-wide counts right after one user's status changes.
function withUser(page: UsersPage, user: AdminUser): UsersPage {
  const before = page.data.find((u) => u.id === user.id)?.status
  const counts = { ...page.counts }
  for (const s of ["pending", "suspended"] as const) {
    if (before === s) counts[s] -= 1
    if (user.status === s) counts[s] += 1
  }
  return { ...page, data: page.data.map((u) => (u.id === user.id ? user : u)), counts }
}

const STATUS_STYLE: Record<UserStatus, string> = {
  active: "border-verdict-authentic/40 bg-verdict-authentic/10 text-verdict-authentic",
  suspended: "border-verdict-false/40 bg-verdict-false/10 text-verdict-false",
  pending: "border-verdict-likely-false/40 bg-verdict-likely-false/10 text-verdict-likely-false",
}

type Pending =
  | { kind: "role"; user: AdminUser; role: Role }
  | { kind: "suspend"; user: AdminUser }
  | null

// FR-ADMIN-02: activate, suspend and change roles. Live, the API filters and pages the
// list (GET /admin/users) and records every change in the audit log (PATCH); in demo
// builds the sample users are filtered and changed locally.
export function UserManagement() {
  const [query, setQuery] = React.useState("")
  const [search, setSearch] = React.useState("")
  const [role, setRole] = React.useState<Role | "">("")
  const [status, setStatus] = React.useState<UserStatus | "">("")
  const [page, setPage] = React.useState(1)
  const { live, data, setData } = useAdminData(
    () => adminApi.users({ q: search || undefined, role: role || undefined, status: status || undefined, page, perPage: PER_PAGE }),
    DEMO,
    [search, role, status, page]
  )
  const users = React.useMemo(() => data?.data ?? [], [data])
  const errorMessage = useApiErrorMessage()

  // Typing searches after a pause, not on every key; any filter change starts at page 1.
  React.useEffect(() => {
    const t = setTimeout(() => {
      setSearch(query.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(t)
  }, [query])
  const [pending, setPending] = React.useState<Pending>(null)
  const [reason, setReason] = React.useState("")
  const t = useTranslations("Admin.users")
  const f = useFormat()
  const tRoles = useTranslations("Roles")
  const tc = useTranslations("Common")
  const ta = useTranslations("Admin")

  // Resolves true once the change is saved (live) or applied (demo); false after an error.
  const update = React.useCallback(
    async (id: string, patch: Pick<Partial<AdminUser>, "role" | "status">): Promise<boolean> => {
      const replace = (u: AdminUser) => setData((d) => (d ? withUser(d, u) : d))
      if (!live) {
        const current = users.find((u) => u.id === id)
        if (current) replace({ ...current, ...patch })
        return true
      }
      try {
        replace(await adminApi.updateUser(id, patch))
        return true
      } catch (e) {
        toast.error(errorMessage(e))
        return false
      }
    },
    [live, users, setData, errorMessage]
  )

  const rows = React.useMemo(() => {
    if (live) return users // filtered by the API
    const q = query.trim().toLowerCase()
    return users.filter(
      (u) =>
        (!q || `${u.name} ${u.email}`.toLowerCase().includes(q)) &&
        (!role || u.role === role) &&
        (!status || u.status === status)
    )
  }, [live, users, query, role, status])

  const columns = React.useMemo<AdminColumn<AdminUser>[]>(
    () => [
      {
        id: "name",
        accessorFn: (u) => u.name,
        sortFn: "alphanumeric",
        header: ({ column }) => <SortableHeader column={column} label={t("columns.user")} />,
        meta: { label: t("columns.user") },
        cell: ({ row: { original: u } }) => (
          <div className="flex min-w-48 items-center gap-3">
            <Avatar className="size-8">
              <AvatarFallback>{initials(u.name)}</AvatarFallback>
            </Avatar>
            <div className="flex flex-col">
              <span className="font-medium">{u.name}</span>
              <span className="text-xs text-muted-foreground">{u.email}</span>
            </div>
          </div>
        ),
      },
      {
        id: "role",
        header: () => t("columns.role"),
        cell: ({ row: { original: u } }) => <Badge variant="outline">{tRoles(u.role)}</Badge>,
      },
      {
        id: "status",
        header: () => t("columns.status"),
        cell: ({ row: { original: u } }) => (
          <span className={cn("inline-flex min-h-5 items-center border px-1.5 text-xs", STATUS_STYLE[u.status])}>
            {t(`statuses.${u.status}`)}
          </span>
        ),
      },
      {
        id: "ratings",
        accessorFn: (u) => u.ratings,
        sortFn: "basic",
        header: ({ column }) => <SortableHeader column={column} label={t("columns.ratings")} />,
        meta: { label: t("columns.ratings") },
        cell: ({ row: { original: u } }) => <span className="font-mono tabular-nums">{u.ratings}</span>,
      },
      {
        id: "lastActive",
        accessorFn: (u) => u.lastActive,
        sortFn: "alphanumeric",
        header: ({ column }) => <SortableHeader column={column} label={t("columns.lastActive")} />,
        meta: { label: t("columns.lastActive") },
        cell: ({ row: { original: u } }) => (
          <span className="text-xs whitespace-nowrap text-muted-foreground">
            {f.date(u.lastActive)} <br /> {t("joined", { date: f.date(u.joined) })}
          </span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">{t("columns.actions")}</span>,
        cell: ({ row: { original: u } }) => (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t("actionsFor", { name: u.name })}>
                <RiMore2Line aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-52">
              <DropdownMenuLabel>{u.name}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {u.status === "pending" && (
                <DropdownMenuItem
                  onSelect={async () => {
                    if (await update(u.id, { status: "active", role: "journalist" })) toast.success(t("approved", { name: u.name }))
                  }}
                >
                  {t("approve")}
                </DropdownMenuItem>
              )}
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>{t("changeRole")}</DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  <DropdownMenuRadioGroup
                    value={u.role}
                    onValueChange={(r) => r !== u.role && setPending({ kind: "role", user: u, role: r as Role })}
                  >
                    {ROLES.map((r) => (
                      <DropdownMenuRadioItem key={r} value={r}>
                        {tRoles(r)}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuSub>
              <DropdownMenuSeparator />
              {u.status === "suspended" ? (
                <DropdownMenuItem
                  onSelect={async () => {
                    if (await update(u.id, { status: "active" })) toast.success(t("reactivated", { name: u.name }))
                  }}
                >
                  {t("reactivate")}
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem variant="destructive" onSelect={() => setPending({ kind: "suspend", user: u })}>
                  {t("suspend")}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [update, t, tRoles, f]
  )

  async function confirmPending() {
    if (!pending) return
    if (pending.kind === "role") {
      if (await update(pending.user.id, { role: pending.role }))
        toast.success(t("roleChanged", { name: pending.user.name, role: tRoles(pending.role) }), { description: ta("loggedInAudit") })
    } else if (await update(pending.user.id, { status: "suspended" })) {
      toast.success(t("suspendedToast", { name: pending.user.name }), { description: t("suspendedBody") })
    }
    setPending(null)
    setReason("")
  }

  const counts = {
    total: live ? (data?.total ?? 0) : users.length,
    suspended: data?.counts.suspended ?? 0,
    pending: data?.counts.pending ?? 0,
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <RiSearchLine className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchPlaceholder")} aria-label={t("searchLabel")} className="pl-9" />
        </div>
        <label htmlFor="users-role" className="sr-only">{t("role")}</label>
        <NativeSelect id="users-role" value={role} onChange={(e) => {
            setRole(e.target.value as Role | "")
            setPage(1)
          }}>
          <NativeSelectOption value="">{t("allRoles")}</NativeSelectOption>
          {ROLES.map((r) => (
            <NativeSelectOption key={r} value={r}>{tRoles(r)}</NativeSelectOption>
          ))}
        </NativeSelect>
        <label htmlFor="users-status" className="sr-only">{t("status")}</label>
        <NativeSelect id="users-status" value={status} onChange={(e) => {
            setStatus(e.target.value as UserStatus | "")
            setPage(1)
          }}>
          <NativeSelectOption value="">{t("allStatuses")}</NativeSelectOption>
          <NativeSelectOption value="active">{t("statuses.active")}</NativeSelectOption>
          <NativeSelectOption value="pending">{t("statuses.pending")}</NativeSelectOption>
          <NativeSelectOption value="suspended">{t("statuses.suspended")}</NativeSelectOption>
        </NativeSelect>
      </div>
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {t("summary", { shown: rows.length, total: counts.total, pending: counts.pending, suspended: counts.suspended })}
      </p>

      <DataTable data={rows} columns={columns} getRowId={(u) => u.id} initialSorting={[{ id: "name", desc: false }]} />
      {live && data && <Pager page={page} total={data.total} perPage={PER_PAGE} onPage={setPage} />}

      <AlertDialog open={pending !== null} onOpenChange={(o) => !o && setPending(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pending?.kind === "role"
                ? t("roleTitle", { name: pending.user.name, role: tRoles(pending.role) })
                : t("suspendTitle", { name: pending?.user.name ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pending?.kind === "role"
                ? pending.role === "expert" || pending.role === "admin"
                  ? t("roleTfa")
                  : t("roleNow")
                : t("suspendBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("reasonPlaceholder")} aria-label={t("reason")} rows={3} />
          <AlertDialogFooter>
            <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={reason.trim().length < 5}
              onClick={confirmPending}
              className={pending?.kind === "suspend" ? "bg-destructive text-white hover:bg-destructive/90" : undefined}
            >
              {tc("confirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

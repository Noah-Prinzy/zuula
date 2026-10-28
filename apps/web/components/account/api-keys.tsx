"use client"

import * as React from "react"
import Link from "next/link"
import { RiAddLine, RiAlertLine, RiFileCopyLine, RiKey2Line } from "@remixicon/react"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { SettingsSection } from "@/components/account/settings-section"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty"
import { Field, FieldError, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { useApiErrorMessage } from "@/hooks/use-api-error-message"
import { useLiveData } from "@/hooks/use-live-data"
import { useRelativeTime } from "@/hooks/use-relative-time"
import { accountApi, accountApiLive } from "@/lib/account-api"
import { useFormat } from "@/lib/format"
import {
  API_RATE_LIMIT,
  SAMPLE_API_KEYS,
  SAMPLE_API_USAGE,
  type ApiKey,
  type ApiScope,
} from "@/lib/mock/account"

// Text lives in Account.apiKeys.scopes.<scope>.
const SCOPES: ApiScope[] = ["submit", "read"]

const MAX_KEYS = 5

// Demo secret; real keys are generated and hashed by the server, shown once.
function demoSecret() {
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(24)), (b) => b.toString(16).padStart(2, "0")).join("")
  return `zl_live_${hex}`
}

async function copy(text: string, success: string, failure: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(success)
  } catch {
    toast.error(failure)
  }
}

function CreateKeyDialog({
  open,
  onOpenChange,
  onCreate,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onCreate: (k: ApiKey) => void
}) {
  const [name, setName] = React.useState("")
  const [scopes, setScopes] = React.useState<ApiScope[]>(["submit", "read"])
  const [error, setError] = React.useState<string | null>(null)
  const [secret, setSecret] = React.useState<string | null>(null)
  const t = useTranslations("Account.apiKeys")
  const tc = useTranslations("Common")
  const errorMessage = useApiErrorMessage()

  function close(o: boolean) {
    onOpenChange(o)
    if (!o) {
      setName("")
      setScopes(["submit", "read"])
      setError(null)
      setSecret(null)
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault()
    if (name.trim().length < 2) return setError(t("nameRequired"))
    if (scopes.length === 0) return setError(t("scopeRequired"))
    if (accountApiLive()) {
      // The API makes the key and returns its secret this once (only a hash is stored).
      try {
        const { secret: real, ...key } = await accountApi.createApiKey({ name: name.trim(), scopes })
        setSecret(real)
        onCreate(key)
      } catch (err) {
        setError(errorMessage(err))
      }
      return
    }
    const s = demoSecret()
    setSecret(s)
    onCreate({
      id: crypto.randomUUID(),
      name: name.trim(),
      prefix: s.slice(0, 12),
      scopes,
      createdAt: new Date().toISOString().slice(0, 10),
      lastUsedAt: null,
    })
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        {secret ? (
          <>
            <DialogHeader>
              <DialogTitle>{t("copyTitle")}</DialogTitle>
              <DialogDescription>{t("copyBody")}</DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-2 border bg-muted/40 p-3">
              <code className="min-w-0 flex-1 font-mono text-sm break-all">{secret}</code>
              <Button variant="outline" size="icon-sm" onClick={() => copy(secret, t("copied"), t("copyFailed"))} aria-label={t("copyKey")}>
                <RiFileCopyLine aria-hidden />
              </Button>
            </div>
            <DialogFooter>
              <Button onClick={() => close(false)}>{t("saved")}</Button>
            </DialogFooter>
          </>
        ) : (
          <form noValidate onSubmit={create} className="flex flex-col gap-4">
            <DialogHeader>
              <DialogTitle>{t("createTitle")}</DialogTitle>
              <DialogDescription>{t("createBody", { limit: API_RATE_LIMIT })}</DialogDescription>
            </DialogHeader>
            <Field>
              <FieldLabel htmlFor="key-name">{t("name")}</FieldLabel>
              <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("namePlaceholder")} autoComplete="off" />
            </Field>
            <FieldSet>
              <FieldLegend variant="label">{t("permissions")}</FieldLegend>
              <div className="flex flex-col gap-3">
                {SCOPES.map((s) => (
                  <div key={s} className="flex items-start gap-2">
                    <Checkbox
                      id={`scope-${s}`}
                      checked={scopes.includes(s)}
                      onCheckedChange={(c) =>
                        setScopes((cur) => (c === true ? [...cur, s] : cur.filter((x) => x !== s)))
                      }
                      className="mt-0.5"
                    />
                    <label htmlFor={`scope-${s}`} className="flex flex-col">
                      <span className="text-sm font-medium">{t(`scopes.${s}.label`)}</span>
                      <span className="font-mono text-xs text-muted-foreground">{t(`scopes.${s}.description`)}</span>
                    </label>
                  </div>
                ))}
              </div>
            </FieldSet>
            {error && <FieldError>{error}</FieldError>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => close(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit">{t("createKey")}</Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

// FR-API-01 / 02: API keys for partners and journalists.
// FR-API-02: partner API keys. Live, the list, usage, creating and revoking go through the API
// (GET/POST/DELETE /me/api-keys, GET /me/api-usage); demo builds keep the samples.
export function ApiKeys() {
  const live = accountApiLive()
  const loaded = useLiveData(live, accountApi.apiKeys, SAMPLE_API_KEYS, [])
  const usageData = useLiveData(live, accountApi.apiUsage, SAMPLE_API_USAGE, [])
  if (!loaded.data || !usageData.data) return <Skeleton className="h-64 w-full" />
  return (
    <ApiKeysView
      live={live}
      initial={loaded.data}
      usage={{ usedThisHour: usageData.data.usedThisHour ?? 0, last24h: usageData.data.last24h ?? 0 }}
    />
  )
}

function ApiKeysView({ live, initial, usage }: { live: boolean; initial: ApiKey[]; usage: typeof SAMPLE_API_USAGE }) {
  const [keys, setKeys] = React.useState(initial)
  const [open, setOpen] = React.useState(false)
  const errorMessage = useApiErrorMessage()
  const pct = Math.round((usage.usedThisHour / API_RATE_LIMIT) * 100)
  const t = useTranslations("Account.apiKeys")
  const tc = useTranslations("Common")
  const f = useFormat()
  const relativeTime = useRelativeTime()

  return (
    <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
      <SettingsSection
        id="keys"
        title={t("keysTitle")}
        description={t("keysDescription")}
        footer={
          <Button onClick={() => setOpen(true)} disabled={keys.length >= MAX_KEYS}>
            <RiAddLine aria-hidden /> {t("createKey")}
          </Button>
        }
      >
        {keys.length === 0 ? (
          <Empty className="border border-dashed">
            <EmptyHeader>
              <EmptyTitle>{t("emptyTitle")}</EmptyTitle>
              <EmptyDescription>{t("emptyBody")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ul className="flex flex-col divide-y border">
            {keys.map((k) => (
              <li key={k.id} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center">
                <RiKey2Line className="hidden size-5 shrink-0 text-muted-foreground sm:block" aria-hidden />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="text-sm font-medium">{k.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{k.prefix}••••••••</span>
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                    {k.scopes.map((s) => (
                      <Badge key={s} variant="outline">
                        {s}
                      </Badge>
                    ))}
                    <span>{t("created", { date: f.date(k.createdAt) })}</span>
                    <span>· {k.lastUsedAt ? t("lastUsed", { when: relativeTime(k.lastUsedAt) }) : t("neverUsed")}</span>
                  </div>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
                      {t("revoke")}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t("revokeTitle", { name: k.name })}</AlertDialogTitle>
                      <AlertDialogDescription>{t("revokeBody")}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>{tc("cancel")}</AlertDialogCancel>
                      <AlertDialogAction
                        className="bg-destructive text-white hover:bg-destructive/90"
                        onClick={async () => {
                          if (live) {
                            try {
                              await accountApi.revokeApiKey(k.id)
                            } catch (e) {
                              toast.error(errorMessage(e))
                              return
                            }
                          }
                          setKeys((ks) => ks.filter((x) => x.id !== k.id))
                          toast.success(t("revoked", { name: k.name }))
                        }}
                      >
                        {t("revokeKey")}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </li>
            ))}
          </ul>
        )}
        {keys.length >= MAX_KEYS && (
          <p className="text-xs text-muted-foreground">{t("maxKeys", { max: MAX_KEYS })}</p>
        )}
      </SettingsSection>

      <div className="flex flex-col gap-6">
        <SettingsSection id="usage" title={t("usageTitle")}>
          <div className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between text-sm">
              <span>{t("thisHour")}</span>
              <span className="font-mono tabular-nums">
                {usage.usedThisHour} / {API_RATE_LIMIT}
              </span>
            </div>
            <Progress value={pct} aria-label={t("usageLabel", { percent: pct })} />
            <p className="text-xs text-muted-foreground">
              {t("usageBody", { count: f.number(usage.last24h) })}
            </p>
          </div>
        </SettingsSection>
        <div className="flex gap-3 border border-verdict-likely-false/40 bg-verdict-likely-false/5 p-4 text-sm">
          <RiAlertLine className="mt-0.5 size-4 shrink-0 text-verdict-likely-false" aria-hidden />
          <p>
            {t.rich("secretNote", {
              code: (chunks) => <code className="font-mono text-xs">{chunks}</code>,
              link: (chunks) => (
                <Link href="/developers" className="text-primary underline underline-offset-2">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        </div>
      </div>

      <CreateKeyDialog open={open} onOpenChange={setOpen} onCreate={(k) => setKeys((ks) => [k, ...ks])} />
    </div>
  )
}

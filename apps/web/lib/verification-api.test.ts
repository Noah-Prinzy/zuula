import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ApiError } from "@/lib/api"
import {
  decideApplication,
  documentExpired,
  documentHref,
  getApplication,
  listApplications,
  verificationApiConfigured,
  type AccreditationApplicationDetail,
} from "@/lib/verification-api"

// Shape copied from a real GET /api/v1/admin/verifications/{id} response (contract tests).
const DETAIL: AccreditationApplicationDetail = {
  id: "acc_3f9a0c1d2e4b5a6c",
  status: "pending",
  requestedRole: "journalist",
  organisation: "Daily Monitor",
  pressCardNumber: "UMC-1234",
  submittedAt: "2026-10-28T09:00:00Z",
  documentCount: 1,
  applicant: {
    id: "u6",
    name: "Amina Nakato",
    email: "amina@example.com",
    role: "public",
    status: "active",
    joined: "2026-05-22",
  },
  documents: [
    {
      index: 0,
      url: "/api/v1/admin/verifications/acc_3f9a0c1d2e4b5a6c/documents/0?expires=1792000000&sig=ab12",
      expiresAt: "2026-10-28T09:10:00Z",
    },
  ],
}

function reply(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
  })
}

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock)
  fetchMock.mockReset()
  vi.stubEnv("NEXT_PUBLIC_API_URL", "http://api.test")
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe("verificationApiConfigured", () => {
  it("is on with an API address and off in a production build without one", () => {
    expect(verificationApiConfigured()).toBe(true)
    vi.stubEnv("NEXT_PUBLIC_API_URL", "")
    vi.stubEnv("NODE_ENV", "production")
    expect(verificationApiConfigured()).toBe(false)
  })
})

describe("listApplications", () => {
  it("gets the queue with credentials and no query by default", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { data: [DETAIL], page: 1, perPage: 20, total: 1 }))
    const page = await listApplications()
    expect(page.total).toBe(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe("http://api.test/api/v1/admin/verifications")
    expect(init).toMatchObject({ method: "GET", credentials: "include" })
  })

  it("sends the status filter and paging", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { data: [], page: 2, perPage: 10, total: 0 }))
    await listApplications({ status: "rejected", page: 2, perPage: 10 })
    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://api.test/api/v1/admin/verifications?status=rejected&page=2&perPage=10"
    )
  })

  it("surfaces a 403 for non-admins as an ApiError", async () => {
    fetchMock.mockResolvedValueOnce(reply(403, { error: { code: "forbidden", message: "Admins only." } }))
    await expect(listApplications()).rejects.toMatchObject({ status: 403, code: "forbidden" })
  })
})

describe("getApplication", () => {
  it("gets one application by id", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, DETAIL))
    await expect(getApplication(DETAIL.id)).resolves.toEqual(DETAIL)
    expect(fetchMock.mock.calls[0][0]).toBe(`http://api.test/api/v1/admin/verifications/${DETAIL.id}`)
  })

  it("encodes the id", async () => {
    fetchMock.mockResolvedValueOnce(reply(404, { error: { code: "not_found", message: "No application." } }))
    await expect(getApplication("a/b")).rejects.toBeInstanceOf(ApiError)
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/v1/admin/verifications/a%2Fb")
  })
})

describe("decideApplication", () => {
  it("posts an approval", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { ...DETAIL, status: "approved" }))
    const result = await decideApplication(DETAIL.id, { decision: "approve" })
    expect(result.status).toBe("approved")
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe(`http://api.test/api/v1/admin/verifications/${DETAIL.id}/decision`)
    expect(init).toMatchObject({ method: "POST", credentials: "include" })
    expect(JSON.parse(String(init?.body))).toEqual({ decision: "approve" })
  })

  it("posts a rejection with its note", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { ...DETAIL, status: "rejected", note: "Expired card." }))
    await decideApplication(DETAIL.id, { decision: "reject", note: "Expired card." })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      decision: "reject",
      note: "Expired card.",
    })
  })

  it("rejects with the API's message when the application was already decided", async () => {
    fetchMock.mockResolvedValueOnce(
      reply(409, { error: { code: "conflict", message: "This application has already been decided." } })
    )
    await expect(decideApplication(DETAIL.id, { decision: "approve" })).rejects.toMatchObject({
      status: 409,
      message: "This application has already been decided.",
    })
  })
})

describe("documents", () => {
  it("resolves a signed path against the API origin", () => {
    expect(documentHref(DETAIL.documents[0])).toBe(`http://api.test${DETAIL.documents[0].url}`)
  })

  it("stays relative when the site proxies the API", () => {
    vi.stubEnv("NEXT_PUBLIC_API_URL", "/")
    expect(documentHref(DETAIL.documents[0])).toBe(DETAIL.documents[0].url)
  })

  it("knows when a link has expired", () => {
    const doc = DETAIL.documents[0]
    expect(documentExpired(doc, new Date("2026-10-28T09:09:59Z"))).toBe(false)
    expect(documentExpired(doc, new Date("2026-10-28T09:10:00Z"))).toBe(true)
  })
})

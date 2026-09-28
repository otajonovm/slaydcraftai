/**
 * SlideCraft AI backend client.
 *
 * Every request carries `Authorization: tma <initData>`; the backend must validate
 * the signature with the bot token (HMAC-SHA256 per Telegram docs) before trusting the user id.
 *
 * When `VITE_API_URL` is empty the client runs in demo mode with an in-memory backend,
 * so the UI can be developed and reviewed without a server.
 *
 * Endpoints:
 *   GET  /me                      -> Profile
 *   GET  /tariffs                 -> Tariff[]
 *   GET  /history?limit=20        -> HistoryItem[]
 *   POST /jobs        {request}   -> Job           (402 when no credits left)
 *   GET  /jobs/:id                -> Job
 *   POST /files/:id/send          -> { ok: true }  (bot sends the file to the user's chat)
 *   POST /payments    {tariff, provider} -> PaymentLink
 */

import { getInitData, getTelegramUser } from './telegram'
import {
  ApiError,
  type ApiErrorCode,
  type DocType,
  type FileFormat,
  type GeneratedFile,
  type GenerationRequest,
  type HistoryItem,
  type Job,
  type JobStage,
  type PaymentLink,
  type PaymentProvider,
  type Profile,
  type Tariff,
} from '@/types'

const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')
const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || 'slaydreferat_aibot'
const REQUEST_TIMEOUT_MS = 20_000

export const isDemoMode = !API_URL

export interface SlideCraftApi {
  getProfile(): Promise<Profile>
  getTariffs(): Promise<Tariff[]>
  getHistory(limit?: number): Promise<HistoryItem[]>
  createJob(request: GenerationRequest): Promise<Job>
  getJob(id: string): Promise<Job>
  sendToChat(fileId: string): Promise<void>
  createPayment(tariffKey: string, provider: PaymentProvider): Promise<PaymentLink>
}

// ---------------------------------------------------------------- HTTP client

function codeForStatus(status: number): ApiErrorCode {
  if (status === 401 || status === 403) return 'unauthorized'
  if (status === 402) return 'no_credits'
  if (status === 409 || status === 429) return 'busy'
  if (status >= 400 && status < 500) return 'bad_request'
  return 'server'
}

const DEFAULT_MESSAGES: Record<ApiErrorCode, string> = {
  unauthorized: "Avtorizatsiya xatosi. Ilovani bot orqali qayta oching.",
  no_credits: 'Generatsiyalar soni tugadi.',
  busy: 'Sizda allaqachon jarayondagi generatsiya bor. Biroz kuting.',
  bad_request: "So'rov noto'g'ri.",
  network: "Internet aloqasi yo'q yoki server javob bermadi.",
  server: "Serverda xatolik yuz berdi. Keyinroq urinib ko'ring.",
}

async function request<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: init.method ?? 'GET',
      headers: {
        Authorization: `tma ${getInitData()}`,
        ...(init.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
      signal: controller.signal,
    })
  } catch {
    throw new ApiError('network', DEFAULT_MESSAGES.network)
  } finally {
    window.clearTimeout(timer)
  }

  if (!res.ok) {
    const code = codeForStatus(res.status)
    let message = DEFAULT_MESSAGES[code]
    try {
      const data = (await res.json()) as { detail?: string; message?: string }
      message = data.detail || data.message || message
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(code, message, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const httpApi: SlideCraftApi = {
  getProfile: () => request<Profile>('/me'),
  getTariffs: () => request<Tariff[]>('/tariffs'),
  getHistory: (limit = 20) => request<HistoryItem[]>(`/history?limit=${limit}`),
  createJob: (req) => request<Job>('/jobs', { method: 'POST', body: req }),
  getJob: (id) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
  sendToChat: async (fileId) => {
    await request<{ ok: boolean }>(`/files/${encodeURIComponent(fileId)}/send`, { method: 'POST' })
  },
  createPayment: (tariff, provider) => request<PaymentLink>('/payments', { method: 'POST', body: { tariff, provider } }),
}

// ---------------------------------------------------------------- demo backend

const DEMO_TARIFFS: Tariff[] = [
  { key: 'single', title: '1 ta hujjat', credits: 1, priceUzs: 5_000 },
  { key: 'student', title: 'Talaba to‘plami', credits: 5, priceUzs: 15_000, badge: 'Ommabop' },
  { key: 'session', title: 'Sessiya to‘plami', credits: 15, priceUzs: 35_000, badge: 'Tejamkor' },
  { key: 'pro', title: 'Pro to‘plam', credits: 50, priceUzs: 69_000 },
]

/** Stage timeline of a simulated job, in milliseconds from start. */
const DEMO_TIMELINE: { at: number; stage: JobStage; progress: number }[] = [
  { at: 0, stage: 'queued', progress: 3 },
  { at: 700, stage: 'outline', progress: 12 },
  { at: 2600, stage: 'writing', progress: 38 },
  { at: 6500, stage: 'rendering', progress: 82 },
  { at: 8200, stage: 'done', progress: 100 },
]

const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

function formatsFor(req: GenerationRequest): FileFormat[] {
  if (req.type === 'presentation') return ['pptx', 'pdf']
  if (req.type === 'referat') return ['docx', 'pdf']
  return ['pdf']
}

function demoFiles(jobId: string, req: GenerationRequest): GeneratedFile[] {
  const base = req.topic.slice(0, 40).trim().replace(/\s+/g, '_') || 'hujjat'
  return formatsFor(req).map((format) => ({
    id: `${jobId}-${format}`,
    name: `${base}.${format}`,
    format,
    sizeBytes: format === 'pdf' ? 480_000 : 1_250_000,
    url: '',
  }))
}

function createDemoApi(): SlideCraftApi {
  const tgUser = getTelegramUser()
  const profile: Profile = {
    user: {
      id: tgUser?.id ?? 1,
      firstName: tgUser?.first_name ?? 'Mehmon',
      lastName: tgUser?.last_name,
      username: tgUser?.username,
      photoUrl: tgUser?.photo_url,
      languageCode: tgUser?.language_code,
      isPremium: Boolean(tgUser?.is_premium),
    },
    balance: { credits: 0, freeCredits: 1, balanceUzs: 0 },
    referralLink: `https://t.me/${BOT_USERNAME}?start=ref_${tgUser?.id ?? 1}`,
    referrals: 0,
  }

  const jobs = new Map<string, { startedAt: number; request: GenerationRequest; isFree: boolean }>()
  const history: HistoryItem[] = [
    {
      id: 'demo-1',
      type: 'presentation',
      topic: "O'zbekistonda raqamli iqtisodiyot",
      createdAt: new Date(Date.now() - 86_400_000).toISOString(),
      status: 'completed',
      files: demoFiles('demo-1', {
        type: 'presentation',
        topic: 'Raqamli iqtisodiyot',
        language: 'uz',
        slides: 10,
        style: 'business',
      }),
    },
  ]

  const snapshot = (id: string): Job => {
    const job = jobs.get(id)
    if (!job) throw new ApiError('bad_request', 'Vazifa topilmadi', 404)
    const elapsed = Date.now() - job.startedAt
    const point = [...DEMO_TIMELINE].reverse().find((p) => elapsed >= p.at) ?? DEMO_TIMELINE[0]!
    const done = point.stage === 'done'
    return {
      id,
      status: done ? 'completed' : 'running',
      stage: point.stage,
      progress: point.progress,
      files: done ? demoFiles(id, job.request) : [],
      isFree: job.isFree,
    }
  }

  return {
    async getProfile() {
      await wait(250)
      return structuredClone(profile)
    },
    async getTariffs() {
      await wait(120)
      return DEMO_TARIFFS
    },
    async getHistory() {
      await wait(200)
      return structuredClone(history)
    },
    async createJob(req) {
      await wait(300)
      const { balance } = profile
      let isFree: boolean
      if (balance.credits > 0) {
        balance.credits -= 1
        isFree = false
      } else if (balance.freeCredits > 0) {
        balance.freeCredits -= 1
        isFree = true
      } else {
        throw new ApiError('no_credits', DEFAULT_MESSAGES.no_credits, 402)
      }
      const id = `demo-${Date.now()}`
      jobs.set(id, { startedAt: Date.now(), request: req, isFree })
      window.setTimeout(() => {
        history.unshift({
          id,
          type: req.type as DocType,
          topic: req.topic,
          createdAt: new Date().toISOString(),
          status: 'completed',
          files: demoFiles(id, req),
        })
      }, DEMO_TIMELINE[DEMO_TIMELINE.length - 1]!.at)
      return snapshot(id)
    },
    async getJob(id) {
      await wait(80)
      return snapshot(id)
    },
    async sendToChat() {
      await wait(400)
    },
    async createPayment(tariffKey, provider) {
      await wait(300)
      const tariff = DEMO_TARIFFS.find((t) => t.key === tariffKey)
      if (tariff) profile.balance.credits += tariff.credits
      return { provider, url: '', transactionId: `demo-tx-${Date.now()}` }
    },
  }
}

export const api: SlideCraftApi = isDemoMode ? createDemoApi() : httpApi
export { BOT_USERNAME }

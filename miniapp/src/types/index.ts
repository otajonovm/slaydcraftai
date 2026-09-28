/** Document kinds the user can order from the dashboard. */
export type DocType = 'presentation' | 'referat' | 'pdf'

/** Output file format produced by the backend. */
export type FileFormat = 'pptx' | 'docx' | 'pdf'

export type Language = 'uz' | 'ru' | 'en'

/** Visual style; the backend maps it onto a presentation theme. */
export type PresentationStyle = 'business' | 'academic' | 'creative'

export type SlideCount = 8 | 10 | 15

/** Length of a referat (matches the bot: short ~5-7 pages, standard ~10-12 pages). */
export type ReferatSize = 'short' | 'standard'

/** Which content a "PDF document" is built from. */
export type PdfSource = 'presentation' | 'referat'

// ---------------------------------------------------------------- user & balance

export interface User {
  id: number
  firstName: string
  lastName?: string
  username?: string
  photoUrl?: string
  languageCode?: string
  isPremium: boolean
}

export interface Balance {
  /** Paid generations left. */
  credits: number
  /** Free generations left (outputs carry a watermark). */
  freeCredits: number
  /** Money balance in so'm. */
  balanceUzs: number
}

export interface Profile {
  user: User
  balance: Balance
  referralLink: string
  referrals: number
}

// ---------------------------------------------------------------- generation requests

interface GenerationBase {
  topic: string
  language: Language
}

export interface PresentationRequest extends GenerationBase {
  type: 'presentation'
  slides: SlideCount
  style: PresentationStyle
}

export interface ReferatRequest extends GenerationBase {
  type: 'referat'
  size: ReferatSize
  /** Optional author details for the title page. */
  author?: string
  subject?: string
}

export interface PdfRequest extends GenerationBase {
  type: 'pdf'
  source: PdfSource
  slides: SlideCount
  style: PresentationStyle
  size: ReferatSize
}

export type GenerationRequest = PresentationRequest | ReferatRequest | PdfRequest

// ---------------------------------------------------------------- jobs & files

export type JobStage = 'queued' | 'outline' | 'writing' | 'rendering' | 'done'

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface GeneratedFile {
  id: string
  name: string
  format: FileFormat
  sizeBytes: number
  /** Absolute download URL (short-lived, signed by the backend). */
  url: string
}

export interface Job {
  id: string
  status: JobStatus
  stage: JobStage
  /** 0..100 */
  progress: number
  files: GeneratedFile[]
  error?: string
  /** True if a free credit was spent (file has a watermark). */
  isFree?: boolean
}

export interface HistoryItem {
  id: string
  type: DocType
  topic: string
  createdAt: string
  status: JobStatus
  files: GeneratedFile[]
}

// ---------------------------------------------------------------- billing

export type PaymentProvider = 'payme' | 'click'

export interface Tariff {
  key: string
  title: string
  credits: number
  priceUzs: number
  /** Optional marketing badge, e.g. "Ommabop". */
  badge?: string
}

export interface PaymentLink {
  provider: PaymentProvider
  url: string
  transactionId: string
}

// ---------------------------------------------------------------- ui

export interface SegmentOption<V> {
  value: V
  label: string
  hint?: string
}

// ---------------------------------------------------------------- errors

export type ApiErrorCode = 'unauthorized' | 'no_credits' | 'busy' | 'bad_request' | 'network' | 'server'

export class ApiError extends Error {
  constructor(
    public readonly code: ApiErrorCode,
    message: string,
    public readonly status = 0,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

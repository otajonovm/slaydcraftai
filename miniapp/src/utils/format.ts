import type { Balance, DocType, FileFormat } from '@/types'

/** 15000 -> "15 000 so'm" */
export function formatUzs(amount: number): string {
  return `${amount.toLocaleString('ru-RU').replace(/\u00A0/g, ' ')} so‘m`
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatRelativeDate(iso: string): string {
  const date = new Date(iso)
  const diffMin = Math.round((Date.now() - date.getTime()) / 60_000)
  if (diffMin < 1) return 'hozirgina'
  if (diffMin < 60) return `${diffMin} daqiqa oldin`
  const diffH = Math.round(diffMin / 60)
  if (diffH < 24) return `${diffH} soat oldin`
  const diffD = Math.round(diffH / 24)
  if (diffD < 7) return `${diffD} kun oldin`
  return date.toLocaleDateString('ru-RU')
}

/** Human-readable balance for the header chip. */
export function describeBalance(b: Balance): { primary: string; secondary?: string } {
  const total = b.credits + b.freeCredits
  if (b.credits > 0) {
    return {
      primary: `${total} ta hujjat`,
      secondary: b.freeCredits > 0 ? `${b.freeCredits} tasi bepul` : undefined,
    }
  }
  if (b.freeCredits > 0) return { primary: `${b.freeCredits} ta bepul urinish` }
  if (b.balanceUzs > 0) return { primary: formatUzs(b.balanceUzs) }
  return { primary: 'Balans: 0' }
}

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  presentation: 'Slayd tayyorlash',
  referat: 'Referat tayyorlash',
  pdf: 'PDF hujjat tayyorlash',
}

export const FORMAT_LABELS: Record<FileFormat, string> = {
  pptx: 'PowerPoint',
  docx: 'Word',
  pdf: 'PDF',
}

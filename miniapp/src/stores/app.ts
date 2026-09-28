import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { api, isDemoMode } from '@/services/api'
import { downloadFile, haptic, openLink, setClosingConfirmation, showAlert } from '@/services/telegram'
import {
  ApiError,
  type DocType,
  type GeneratedFile,
  type GenerationRequest,
  type HistoryItem,
  type Job,
  type Language,
  type PaymentProvider,
  type PdfSource,
  type PresentationStyle,
  type Profile,
  type ReferatSize,
  type SlideCount,
  type Tariff,
} from '@/types'

export type View = 'home' | 'form'

export interface FormState {
  topic: string
  language: Language
  slides: SlideCount
  style: PresentationStyle
  size: ReferatSize
  source: PdfSource
  author: string
  subject: string
}

export const TOPIC_MIN = 3
export const TOPIC_MAX = 200

const POLL_INTERVAL_MS = 1200
const POLL_TIMEOUT_MS = 8 * 60_000

export const useAppStore = defineStore('app', () => {
  // ------------------------------------------------------------ state
  const profile = ref<Profile | null>(null)
  const tariffs = ref<Tariff[]>([])
  const history = ref<HistoryItem[]>([])
  const booting = ref(true)
  const bootError = ref<string | null>(null)
  const historyLoading = ref(false)

  const view = ref<View>('home')
  const docType = ref<DocType>('presentation')
  const form = reactive<FormState>({
    topic: '',
    language: 'uz',
    slides: 10,
    style: 'business',
    size: 'standard',
    source: 'presentation',
    author: '',
    subject: '',
  })

  const job = ref<Job | null>(null)
  const progressOpen = ref(false)
  const submitting = ref(false)
  const tariffOpen = ref(false)
  const paying = ref<string | null>(null)
  const toast = ref<{ text: string; kind: 'success' | 'error' } | null>(null)

  let pollTimer: number | undefined
  let toastTimer: number | undefined

  // ------------------------------------------------------------ getters
  const totalCredits = computed(() => {
    const b = profile.value?.balance
    return b ? b.credits + b.freeCredits : 0
  })
  const topicValid = computed(() => {
    const len = form.topic.trim().length
    return len >= TOPIC_MIN && len <= TOPIC_MAX
  })
  const isGenerating = computed(() => job.value?.status === 'pending' || job.value?.status === 'running')

  // ------------------------------------------------------------ helpers
  function notify(text: string, kind: 'success' | 'error' = 'success'): void {
    toast.value = { text, kind }
    window.clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => (toast.value = null), 2800)
  }

  function buildRequest(): GenerationRequest {
    const base = { topic: form.topic.trim(), language: form.language }
    switch (docType.value) {
      case 'presentation':
        return { ...base, type: 'presentation', slides: form.slides, style: form.style }
      case 'referat':
        return {
          ...base,
          type: 'referat',
          size: form.size,
          author: form.author.trim() || undefined,
          subject: form.subject.trim() || undefined,
        }
      case 'pdf':
        return { ...base, type: 'pdf', source: form.source, slides: form.slides, style: form.style, size: form.size }
    }
  }

  // ------------------------------------------------------------ actions
  async function bootstrap(): Promise<void> {
    booting.value = true
    bootError.value = null
    try {
      const [p, t] = await Promise.all([api.getProfile(), api.getTariffs()])
      profile.value = p
      tariffs.value = t
      void loadHistory()
    } catch (e) {
      bootError.value = e instanceof ApiError ? e.message : 'Yuklashda xatolik yuz berdi'
    } finally {
      booting.value = false
    }
  }

  async function refreshProfile(): Promise<void> {
    try {
      profile.value = await api.getProfile()
    } catch {
      /* keep the previous value */
    }
  }

  async function loadHistory(): Promise<void> {
    historyLoading.value = true
    try {
      history.value = await api.getHistory(20)
    } catch {
      /* history is non-critical */
    } finally {
      historyLoading.value = false
    }
  }

  function openForm(type: DocType): void {
    haptic.tap()
    docType.value = type
    view.value = 'form'
  }

  function goHome(): void {
    view.value = 'home'
  }

  function openTariffs(): void {
    haptic.tap()
    tariffOpen.value = true
  }

  async function generate(): Promise<void> {
    if (submitting.value || isGenerating.value) return
    if (!topicValid.value) {
      haptic.error()
      notify(`Mavzu ${TOPIC_MIN}–${TOPIC_MAX} belgi oralig‘ida bo‘lsin`, 'error')
      return
    }
    if (profile.value && totalCredits.value <= 0) {
      haptic.warning()
      tariffOpen.value = true
      return
    }

    submitting.value = true
    try {
      job.value = await api.createJob(buildRequest())
      progressOpen.value = true
      setClosingConfirmation(true)
      void refreshProfile()
      schedulePoll(Date.now())
    } catch (e) {
      if (e instanceof ApiError && e.code === 'no_credits') {
        haptic.warning()
        tariffOpen.value = true
      } else {
        haptic.error()
        notify(e instanceof ApiError ? e.message : 'Xatolik yuz berdi', 'error')
      }
    } finally {
      submitting.value = false
    }
  }

  function schedulePoll(startedAt: number): void {
    window.clearTimeout(pollTimer)
    pollTimer = window.setTimeout(() => void poll(startedAt), POLL_INTERVAL_MS)
  }

  async function poll(startedAt: number): Promise<void> {
    const current = job.value
    if (!current) return
    try {
      const next = await api.getJob(current.id)
      if (next.stage !== current.stage && next.status === 'running') haptic.select()
      job.value = next
      if (next.status === 'completed') {
        haptic.success()
        setClosingConfirmation(false)
        void refreshProfile()
        void loadHistory()
        return
      }
      if (next.status === 'failed') {
        haptic.error()
        setClosingConfirmation(false)
        void refreshProfile()
        return
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.code === 'network')) {
        job.value = { ...current, status: 'failed', error: e instanceof ApiError ? e.message : 'Xatolik' }
        setClosingConfirmation(false)
        return
      }
    }
    if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
      job.value = { ...current, status: 'failed', error: 'Kutish vaqti tugadi. Tarixdan tekshirib ko‘ring.' }
      setClosingConfirmation(false)
      return
    }
    schedulePoll(startedAt)
  }

  function closeProgress(): void {
    if (isGenerating.value) return
    window.clearTimeout(pollTimer)
    progressOpen.value = false
    if (job.value?.status === 'completed') {
      form.topic = ''
      view.value = 'home'
    }
    job.value = null
  }

  async function download(file: GeneratedFile): Promise<void> {
    haptic.tap('medium')
    if (isDemoMode || !file.url) {
      await showAlert('Demo rejim: haqiqiy fayl backend ulanganda yuklab olinadi.')
      return
    }
    const ok = await downloadFile(file.url, file.name)
    if (ok) notify('Yuklab olish boshlandi')
  }

  async function sendToChat(file: GeneratedFile): Promise<void> {
    haptic.tap('medium')
    try {
      await api.sendToChat(file.id)
      haptic.success()
      notify('Fayl Telegram chatga yuborildi ✅')
    } catch (e) {
      haptic.error()
      notify(e instanceof ApiError ? e.message : 'Yuborib bo‘lmadi', 'error')
    }
  }

  async function buy(tariff: Tariff, provider: PaymentProvider): Promise<void> {
    if (paying.value) return
    haptic.tap('medium')
    paying.value = `${tariff.key}:${provider}`
    try {
      const link = await api.createPayment(tariff.key, provider)
      if (link.url) {
        openLink(link.url)
      } else {
        haptic.success()
        notify(`Demo: +${tariff.credits} ta hujjat qo‘shildi`)
        tariffOpen.value = false
      }
      void refreshProfile()
    } catch (e) {
      haptic.error()
      notify(e instanceof ApiError ? e.message : 'To‘lovni boshlab bo‘lmadi', 'error')
    } finally {
      paying.value = null
    }
  }

  return {
    profile,
    tariffs,
    history,
    booting,
    bootError,
    historyLoading,
    view,
    docType,
    form,
    job,
    progressOpen,
    submitting,
    tariffOpen,
    paying,
    toast,
    totalCredits,
    topicValid,
    isGenerating,
    notify,
    bootstrap,
    refreshProfile,
    loadHistory,
    openForm,
    goHome,
    openTariffs,
    generate,
    closeProgress,
    download,
    sendToChat,
    buy,
  }
})

/**
 * Thin, dependency-free wrapper around `window.Telegram.WebApp`.
 *
 * Every call is guarded, so the app also runs in a normal browser (dev mode)
 * where the Telegram object is missing or reports an old Bot API version.
 */

// ---------------------------------------------------------------- SDK typings (subset we use)

type HapticImpact = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'
type HapticNotification = 'error' | 'success' | 'warning'

interface TgThemeParams {
  bg_color?: string
  secondary_bg_color?: string
  text_color?: string
  hint_color?: string
  link_color?: string
  button_color?: string
  button_text_color?: string
  header_bg_color?: string
  section_bg_color?: string
  destructive_text_color?: string
}

interface TgWebAppUser {
  id: number
  first_name: string
  last_name?: string
  username?: string
  language_code?: string
  is_premium?: boolean
  photo_url?: string
}

interface TgBottomButton {
  text: string
  isVisible: boolean
  isActive: boolean
  isProgressVisible: boolean
  setParams(params: {
    text?: string
    color?: string
    text_color?: string
    is_active?: boolean
    is_visible?: boolean
    has_shine_effect?: boolean
  }): TgBottomButton
  show(): TgBottomButton
  hide(): TgBottomButton
  enable(): TgBottomButton
  disable(): TgBottomButton
  showProgress(leaveActive?: boolean): TgBottomButton
  hideProgress(): TgBottomButton
  onClick(cb: () => void): TgBottomButton
  offClick(cb: () => void): TgBottomButton
}

interface TgBackButton {
  isVisible: boolean
  show(): TgBackButton
  hide(): TgBackButton
  onClick(cb: () => void): TgBackButton
  offClick(cb: () => void): TgBackButton
}

interface TgWebApp {
  initData: string
  initDataUnsafe: { user?: TgWebAppUser; start_param?: string }
  version: string
  platform: string
  colorScheme: 'light' | 'dark'
  themeParams: TgThemeParams
  isExpanded: boolean
  MainButton: TgBottomButton
  BackButton: TgBackButton
  HapticFeedback: {
    impactOccurred(style: HapticImpact): void
    notificationOccurred(type: HapticNotification): void
    selectionChanged(): void
  }
  ready(): void
  expand(): void
  close(): void
  isVersionAtLeast(version: string): boolean
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  setBottomBarColor?(color: string): void
  disableVerticalSwipes?(): void
  enableClosingConfirmation(): void
  disableClosingConfirmation(): void
  onEvent(event: string, cb: () => void): void
  offEvent(event: string, cb: () => void): void
  openLink(url: string, options?: { try_instant_view?: boolean }): void
  openTelegramLink(url: string): void
  showAlert(message: string, cb?: () => void): void
  showConfirm(message: string, cb: (ok: boolean) => void): void
  downloadFile?(params: { url: string; file_name: string }, cb?: (accepted: boolean) => void): void
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TgWebApp }
  }
}

// ---------------------------------------------------------------- core

const tg: TgWebApp | undefined = window.Telegram?.WebApp

/** True when running inside a real Telegram client (initData is signed by Telegram). */
export const isTelegram = Boolean(tg && tg.initData)

const supports = (version: string): boolean => Boolean(tg && isTelegram && tg.isVersionAtLeast(version))

export const BRAND = {
  blue: '#2563EB',
  violet: '#7C3AED',
} as const

/** Raw signed init data, sent to the backend as `Authorization: tma <initData>`. */
export function getInitData(): string {
  return tg?.initData ?? ''
}

export function getTelegramUser(): TgWebAppUser | undefined {
  return tg?.initDataUnsafe.user
}

export function getStartParam(): string | undefined {
  return tg?.initDataUnsafe.start_param
}

// ---------------------------------------------------------------- theme

export type ColorScheme = 'light' | 'dark'

function systemScheme(): ColorScheme {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function getColorScheme(): ColorScheme {
  return isTelegram && tg ? tg.colorScheme : systemScheme()
}

/** Toggles the `dark` class and syncs Telegram's header/background with our palette. */
function applyTheme(): void {
  const scheme = getColorScheme()
  const root = document.documentElement
  root.classList.toggle('dark', scheme === 'dark')
  root.style.colorScheme = scheme

  if (!tg || !isTelegram) return
  const bg = tg.themeParams.secondary_bg_color ?? (scheme === 'dark' ? '#0B0F1A' : '#F2F4F8')
  if (supports('6.1')) {
    tg.setHeaderColor(bg)
    tg.setBackgroundColor(bg)
  }
  if (supports('7.10')) tg.setBottomBarColor?.(bg)
}

export function onThemeChange(cb: (scheme: ColorScheme) => void): () => void {
  const handler = () => {
    applyTheme()
    cb(getColorScheme())
  }
  if (tg && isTelegram) {
    tg.onEvent('themeChanged', handler)
    return () => tg.offEvent('themeChanged', handler)
  }
  const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
  mq?.addEventListener('change', handler)
  return () => mq?.removeEventListener('change', handler)
}

/** Call once before mounting the app. */
export function initTelegram(): void {
  applyTheme()
  if (!tg || !isTelegram) return
  tg.ready()
  tg.expand()
  if (supports('7.7')) tg.disableVerticalSwipes?.()
}

// ---------------------------------------------------------------- haptics

export const haptic = {
  /** Light tap for regular buttons and cards. */
  tap(style: HapticImpact = 'light'): void {
    if (supports('6.1')) tg!.HapticFeedback.impactOccurred(style)
  },
  /** Tick for toggles, chips and segmented controls. */
  select(): void {
    if (supports('6.1')) tg!.HapticFeedback.selectionChanged()
  },
  success(): void {
    if (supports('6.1')) tg!.HapticFeedback.notificationOccurred('success')
  },
  warning(): void {
    if (supports('6.1')) tg!.HapticFeedback.notificationOccurred('warning')
  },
  error(): void {
    if (supports('6.1')) tg!.HapticFeedback.notificationOccurred('error')
  },
}

// ---------------------------------------------------------------- main button

export interface MainButtonState {
  text: string
  visible: boolean
  enabled: boolean
  loading: boolean
}

let mainButtonHandler: (() => void) | null = null

/** Whether the native Telegram MainButton is used (otherwise the app renders its own bottom button). */
export const hasNativeMainButton = isTelegram

export const mainButton = {
  /** Replaces the current click handler (only one handler is active at a time). */
  onClick(cb: () => void): void {
    if (!tg || !isTelegram) return
    if (mainButtonHandler) tg.MainButton.offClick(mainButtonHandler)
    mainButtonHandler = () => {
      haptic.tap('medium')
      cb()
    }
    tg.MainButton.onClick(mainButtonHandler)
  },

  offClick(): void {
    if (tg && isTelegram && mainButtonHandler) tg.MainButton.offClick(mainButtonHandler)
    mainButtonHandler = null
  },

  update(state: MainButtonState): void {
    if (!tg || !isTelegram) return
    const btn = tg.MainButton
    btn.setParams({
      text: state.text,
      color: state.enabled ? BRAND.blue : '#94A3B8',
      text_color: '#FFFFFF',
      is_active: state.enabled && !state.loading,
      is_visible: state.visible,
      ...(supports('7.10') ? { has_shine_effect: state.enabled && !state.loading } : {}),
    })
    if (state.loading) btn.showProgress(false)
    else btn.hideProgress()
  },

  hide(): void {
    if (tg && isTelegram) tg.MainButton.hide()
  },
}

// ---------------------------------------------------------------- back button

let backHandler: (() => void) | null = null

export const backButton = {
  show(cb: () => void): void {
    if (!supports('6.1')) return
    if (backHandler) tg!.BackButton.offClick(backHandler)
    backHandler = () => {
      haptic.tap()
      cb()
    }
    tg!.BackButton.onClick(backHandler)
    tg!.BackButton.show()
  },
  hide(): void {
    if (!supports('6.1')) return
    if (backHandler) tg!.BackButton.offClick(backHandler)
    backHandler = null
    tg!.BackButton.hide()
  },
}

// ---------------------------------------------------------------- misc helpers

/** Prevents accidental swipe-close while a document is being generated. */
export function setClosingConfirmation(enabled: boolean): void {
  if (!supports('6.2')) return
  if (enabled) tg!.enableClosingConfirmation()
  else tg!.disableClosingConfirmation()
}

/**
 * Downloads a file. Uses Telegram's native downloader (Bot API 8.0+),
 * otherwise opens the URL in the external browser.
 */
export function downloadFile(url: string, fileName: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (supports('8.0') && tg!.downloadFile) {
      tg!.downloadFile({ url, file_name: fileName }, (accepted) => resolve(accepted))
      return
    }
    if (tg && isTelegram) {
      tg.openLink(url)
      resolve(true)
      return
    }
    const a = document.createElement('a')
    a.href = url
    a.download = fileName
    a.rel = 'noopener'
    a.target = '_blank'
    document.body.appendChild(a)
    a.click()
    a.remove()
    resolve(true)
  })
}

export function openLink(url: string): void {
  if (tg && isTelegram) tg.openLink(url)
  else window.open(url, '_blank', 'noopener')
}

export function openTelegramLink(url: string): void {
  if (tg && isTelegram) tg.openTelegramLink(url)
  else window.open(url, '_blank', 'noopener')
}

export function showAlert(message: string): Promise<void> {
  return new Promise((resolve) => {
    if (supports('6.2')) tg!.showAlert(message, () => resolve())
    else {
      window.alert(message)
      resolve()
    }
  })
}

export function closeApp(): void {
  if (tg && isTelegram) tg.close()
}

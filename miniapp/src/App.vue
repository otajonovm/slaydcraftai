<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch, watchEffect } from 'vue'
import { CircleAlert, CircleCheck, RefreshCw } from 'lucide-vue-next'
import Header from './components/Header.vue'
import DocTypeSelector from './components/DocTypeSelector.vue'
import HistoryList from './components/HistoryList.vue'
import GenerateForm from './components/GenerateForm.vue'
import ProgressModal from './components/ProgressModal.vue'
import TariffModal from './components/TariffModal.vue'
import { useAppStore } from './stores/app'
import { BOT_USERNAME, isDemoMode } from './services/api'
import { backButton, haptic, mainButton, onThemeChange, openTelegramLink } from './services/telegram'
import type { Tariff } from './types'

const store = useAppStore()

// ------------------------------------------------------------ Telegram MainButton

const mainButtonVisible = computed(
  () => store.view === 'form' && !store.progressOpen && !store.tariffOpen && !store.booting,
)

watchEffect(() => {
  mainButton.update({
    text: store.submitting ? 'Yuborilmoqda...' : 'Generatsiya qilish 🚀',
    visible: mainButtonVisible.value,
    enabled: store.topicValid,
    loading: store.submitting,
  })
})

// ------------------------------------------------------------ Telegram BackButton

function handleBack(): void {
  if (store.tariffOpen) store.tariffOpen = false
  else if (store.progressOpen) store.closeProgress()
  else store.goHome()
}

const needsBack = computed(
  () => store.view === 'form' || store.tariffOpen || (store.progressOpen && !store.isGenerating),
)

watch(
  needsBack,
  (show) => {
    if (show) backButton.show(handleBack)
    else backButton.hide()
  },
  { immediate: true },
)

// ------------------------------------------------------------ actions

function payByCard(tariff: Tariff): void {
  haptic.tap('medium')
  store.tariffOpen = false
  const bot = store.profile?.botUsername || BOT_USERNAME
  openTelegramLink(`https://t.me/${bot}?start=buy_${tariff.key}`)
}

function shareReferral(): void {
  haptic.tap()
  const link = store.profile?.referralLink ?? `https://t.me/${BOT_USERNAME}`
  const text = 'SlideCraft AI — slayd va referatlarni 1 daqiqada tayyorlaydigan bot. Sinab ko‘ring!'
  openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`)
}

// ------------------------------------------------------------ lifecycle

let stopThemeWatch: (() => void) | undefined

onMounted(() => {
  mainButton.onClick(() => void store.generate())
  stopThemeWatch = onThemeChange(() => {})
  void store.bootstrap()
})

onBeforeUnmount(() => {
  mainButton.offClick()
  mainButton.hide()
  backButton.hide()
  stopThemeWatch?.()
})

watch(
  () => store.view,
  () => window.scrollTo({ top: 0 }),
)
</script>

<template>
  <div class="relative mx-auto min-h-screen w-full max-w-lg overflow-x-hidden">
    <!-- Ambient brand glow -->
    <div class="pointer-events-none fixed inset-x-0 top-0 -z-0 mx-auto h-72 max-w-lg" aria-hidden="true">
      <div class="absolute -top-24 -left-16 size-72 rounded-full bg-brand-blue/20 blur-3xl dark:bg-brand-blue/25" />
      <div class="absolute -top-16 -right-20 size-64 rounded-full bg-brand-violet/20 blur-3xl dark:bg-brand-violet/25" />
    </div>

    <main class="relative z-10 px-4 pt-[calc(var(--safe-top)+0.75rem)] pb-8">
      <!-- Boot error -->
      <div v-if="store.bootError" class="flex min-h-[70vh] flex-col items-center justify-center text-center">
        <span class="mb-4 flex size-16 items-center justify-center rounded-full bg-app-danger/10 text-app-danger">
          <CircleAlert class="size-8" />
        </span>
        <h1 class="text-[20px] font-bold">Ulanib bo‘lmadi</h1>
        <p class="mt-1 max-w-xs text-[14px] text-app-hint">{{ store.bootError }}</p>
        <button
          type="button"
          class="pressable bg-brand-gradient mt-6 flex h-12 items-center gap-2 rounded-2xl px-6 font-semibold text-white"
          @click="store.bootstrap()"
        >
          <RefreshCw class="size-4" />
          Qayta urinish
        </button>
      </div>

      <Transition v-else name="view" mode="out-in">
        <!-- Dashboard -->
        <div v-if="store.view === 'home'" key="home" class="space-y-6">
          <Header
            :user="store.profile?.user ?? null"
            :balance="store.profile?.balance ?? null"
            :loading="store.booting"
            @open-tariffs="store.openTariffs()"
          />

          <div class="px-1">
            <h1 class="text-[28px] leading-tight font-bold tracking-tight">
              <span class="text-brand-gradient">SlideCraft AI</span>
            </h1>
            <p class="mt-1 text-[15px] text-app-hint">Slayd va referatlarni 1–3 daqiqada tayyorlang</p>
          </div>

          <DocTypeSelector @select="store.openForm" />

          <HistoryList :items="store.history" :loading="store.historyLoading" @download="store.download" />

          <p v-if="isDemoMode" class="text-center text-[12px] text-app-hint">
            Demo rejim — backend ulanmagan (VITE_API_URL)
          </p>
        </div>

        <!-- Generation form -->
        <GenerateForm v-else key="form" />
      </Transition>
    </main>

    <ProgressModal
      :open="store.progressOpen"
      :job="store.job"
      :doc-type="store.docType"
      @close="store.closeProgress()"
      @download="store.download"
      @send="store.sendToChat"
    />

    <TariffModal
      :open="store.tariffOpen"
      :tariffs="store.tariffs"
      :credits="store.totalCredits"
      :paying="store.paying"
      :providers="store.profile?.paymentProviders ?? []"
      @close="store.tariffOpen = false"
      @buy="store.buy"
      @pay-by-card="payByCard"
      @referral="shareReferral"
    />

    <!-- Toast -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="store.toast"
          role="status"
          class="glass fixed inset-x-4 top-[calc(var(--safe-top)+0.75rem)] z-[60] mx-auto flex max-w-sm items-center gap-2.5 rounded-2xl px-4 py-3 text-[14px] font-medium shadow-xl"
        >
          <CircleCheck v-if="store.toast.kind === 'success'" class="size-5 shrink-0 text-emerald-500" />
          <CircleAlert v-else class="size-5 shrink-0 text-app-danger" />
          {{ store.toast.text }}
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

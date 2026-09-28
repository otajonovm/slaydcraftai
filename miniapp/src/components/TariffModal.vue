<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CreditCard, Gift, Loader2, Sparkles, Zap } from 'lucide-vue-next'
import BottomSheet from './ui/BottomSheet.vue'
import { haptic } from '@/services/telegram'
import type { PaymentProvider, Tariff } from '@/types'
import { formatUzs } from '@/utils/format'

const props = defineProps<{
  open: boolean
  tariffs: Tariff[]
  /** Total generations left; 0 turns the sheet into a paywall. */
  credits: number
  /** `${tariffKey}:${provider}` of the payment being created. */
  paying: string | null
}>()

const emit = defineEmits<{
  close: []
  buy: [tariff: Tariff, provider: PaymentProvider]
  'pay-by-card': []
  referral: []
}>()

const selectedKey = ref<string>('')

const selected = computed(() => props.tariffs.find((t) => t.key === selectedKey.value) ?? props.tariffs[0])
const basePrice = computed(() => props.tariffs.find((t) => t.credits === 1)?.priceUzs ?? 0)

watch(
  () => [props.open, props.tariffs] as const,
  ([open, tariffs]) => {
    if (open && !tariffs.some((t) => t.key === selectedKey.value)) {
      selectedKey.value = (tariffs.find((t) => t.badge) ?? tariffs[0])?.key ?? ''
    }
  },
  { immediate: true },
)

function pick(t: Tariff): void {
  haptic.select()
  selectedKey.value = t.key
}

function perUnit(t: Tariff): number {
  return Math.round(t.priceUzs / t.credits)
}

function discount(t: Tariff): number {
  if (!basePrice.value || t.credits <= 1) return 0
  return Math.round((1 - t.priceUzs / (basePrice.value * t.credits)) * 100)
}

function isPaying(provider: PaymentProvider): boolean {
  return props.paying === `${selected.value?.key}:${provider}`
}
</script>

<template>
  <BottomSheet :open="open" labelledby="tariff-title" @close="emit('close')">
    <div class="pt-1 pb-2">
      <div class="mb-5 text-center">
        <span
          class="mx-auto mb-3 flex size-14 items-center justify-center rounded-2xl text-white shadow-xl"
          :class="credits <= 0 ? 'bg-gradient-to-br from-amber-500 to-orange-600 shadow-orange-500/30' : 'bg-brand-gradient shadow-brand-violet/30'"
        >
          <Zap v-if="credits <= 0" class="size-7" />
          <Sparkles v-else class="size-7" />
        </span>
        <h2 id="tariff-title" class="text-[20px] font-bold">
          {{ credits <= 0 ? 'Generatsiyalar tugadi' : 'Balansni to‘ldirish' }}
        </h2>
        <p class="mt-1 text-[14px] text-app-hint">
          {{
            credits <= 0
              ? 'Davom etish uchun o‘zingizga mos paketni tanlang'
              : `Hozir sizda ${credits} ta generatsiya bor`
          }}
        </p>
      </div>

      <div class="space-y-2.5" role="radiogroup" aria-label="Tariflar">
        <button
          v-for="t in tariffs"
          :key="t.key"
          type="button"
          role="radio"
          :aria-checked="t.key === selected?.key"
          class="pressable relative flex w-full items-center gap-3 rounded-2xl p-4 text-left ring-1 transition-all"
          :class="
            t.key === selected?.key
              ? 'bg-brand-blue/[0.06] ring-2 ring-brand-blue'
              : 'bg-app-card ring-app-border'
          "
          @click="pick(t)"
        >
          <span
            class="flex size-5 shrink-0 items-center justify-center rounded-full ring-2 transition-colors"
            :class="t.key === selected?.key ? 'bg-brand-blue ring-brand-blue' : 'ring-app-hint/40'"
          >
            <span v-if="t.key === selected?.key" class="size-2 rounded-full bg-white" />
          </span>

          <span class="min-w-0 flex-1">
            <span class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span class="text-[16px] font-semibold whitespace-nowrap">{{ t.title }}</span>
              <span
                v-if="t.badge"
                class="bg-brand-gradient rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide text-white uppercase"
              >
                {{ t.badge }}
              </span>
            </span>
            <span class="text-[13px] text-app-hint">
              {{ t.credits }} ta hujjat
              <template v-if="t.credits > 1"> · {{ formatUzs(perUnit(t)) }} / dona</template>
            </span>
          </span>

          <span class="shrink-0 text-right">
            <span class="block text-[16px] font-bold tabular-nums">{{ formatUzs(t.priceUzs) }}</span>
            <span v-if="discount(t) > 0" class="text-[12px] font-semibold text-emerald-600 dark:text-emerald-400">
              −{{ discount(t) }}%
            </span>
          </span>
        </button>
      </div>

      <div class="mt-5 grid grid-cols-2 gap-2.5">
        <button
          type="button"
          class="pressable flex h-13 items-center justify-center gap-2 rounded-2xl bg-[#00BAC7] text-[16px] font-bold text-white shadow-lg shadow-[#00BAC7]/25 disabled:opacity-60"
          :disabled="!selected || !!paying"
          @click="selected && emit('buy', selected, 'payme')"
        >
          <Loader2 v-if="isPaying('payme')" class="size-5 animate-spin" />
          <template v-else>Payme</template>
        </button>
        <button
          type="button"
          class="pressable flex h-13 items-center justify-center gap-2 rounded-2xl bg-[#0073FF] text-[16px] font-bold text-white shadow-lg shadow-[#0073FF]/25 disabled:opacity-60"
          :disabled="!selected || !!paying"
          @click="selected && emit('buy', selected, 'click')"
        >
          <Loader2 v-if="isPaying('click')" class="size-5 animate-spin" />
          <template v-else>Click</template>
        </button>
      </div>

      <button
        type="button"
        class="pressable mt-2.5 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-app-text/[0.06] text-[15px] font-semibold"
        @click="emit('pay-by-card')"
      >
        <CreditCard class="size-4" />
        Karta orqali (chek yuborish)
      </button>

      <button
        type="button"
        class="mt-3 flex w-full items-center justify-center gap-1.5 py-2 text-[14px] font-medium text-app-link"
        @click="emit('referral')"
      >
        <Gift class="size-4" />
        Do‘st taklif qiling — bepul generatsiya oling
      </button>
    </div>
  </BottomSheet>
</template>

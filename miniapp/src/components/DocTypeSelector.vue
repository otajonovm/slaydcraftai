<script setup lang="ts">
import type { Component } from 'vue'
import { ChevronRight, FileDown, FileText, Presentation } from 'lucide-vue-next'
import type { DocType } from '@/types'

defineEmits<{ select: [type: DocType] }>()

interface DocCard {
  type: DocType
  title: string
  subtitle: string
  format: string
  icon: Component
  /** Gradient of the icon tile. */
  tile: string
  /** Soft glow in the card corner. */
  glow: string
}

const cards: DocCard[] = [
  {
    type: 'presentation',
    title: 'Slayd / Taqdimot',
    subtitle: '8–15 slayd, 3 xil dizayn, spiker matni bilan',
    format: '.pptx',
    icon: Presentation,
    tile: 'from-[#2563EB] to-[#4F46E5]',
    glow: 'bg-[#2563EB]',
  },
  {
    type: 'referat',
    title: 'Referat / Kurs ishi',
    subtitle: 'OTM standarti: titul, reja, bo‘limlar, adabiyotlar',
    format: '.docx',
    icon: FileText,
    tile: 'from-[#4F46E5] to-[#7C3AED]',
    glow: 'bg-[#7C3AED]',
  },
  {
    type: 'pdf',
    title: 'PDF hujjat',
    subtitle: 'Slayd yoki referatni tayyor PDF ko‘rinishida oling',
    format: '.pdf',
    icon: FileDown,
    tile: 'from-[#7C3AED] to-[#C026D3]',
    glow: 'bg-[#C026D3]',
  },
]
</script>

<template>
  <section aria-labelledby="doc-types-title" class="space-y-3">
    <h2 id="doc-types-title" class="px-1 text-[13px] font-medium tracking-wide text-app-hint uppercase">
      Nima tayyorlaymiz?
    </h2>

    <button
      v-for="(card, i) in cards"
      :key="card.type"
      type="button"
      class="pressable group relative flex w-full items-center gap-4 overflow-hidden rounded-3xl bg-app-card p-4 text-left shadow-[0_4px_24px_rgba(15,23,42,0.06)] ring-1 ring-app-border"
      :class="i === 0 ? 'min-h-28' : 'min-h-24'"
      @click="$emit('select', card.type)"
    >
      <span
        class="pointer-events-none absolute -top-10 -right-10 size-32 rounded-full opacity-[0.12] blur-2xl"
        :class="card.glow"
        aria-hidden="true"
      />
      <span
        class="flex shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br text-white shadow-lg shadow-brand-blue/20"
        :class="[card.tile, i === 0 ? 'size-16' : 'size-14']"
      >
        <component :is="card.icon" :class="i === 0 ? 'size-8' : 'size-7'" :stroke-width="1.8" />
      </span>

      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-2">
          <span class="text-[17px] font-semibold">{{ card.title }}</span>
          <span class="rounded-md bg-app-text/[0.06] px-1.5 py-0.5 font-mono text-[11px] text-app-hint">
            {{ card.format }}
          </span>
        </span>
        <span class="mt-1 block text-[13px] leading-snug text-app-hint">{{ card.subtitle }}</span>
      </span>

      <ChevronRight class="size-5 shrink-0 text-app-hint/60 transition-transform group-active:translate-x-0.5" />
    </button>
  </section>
</template>

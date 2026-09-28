<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ChevronLeft, FileDown, FileText, Lightbulb, Presentation, Rocket, Loader2 } from 'lucide-vue-next'
import SegmentedControl from './ui/SegmentedControl.vue'
import { TOPIC_MAX, TOPIC_MIN, useAppStore } from '@/stores/app'
import { haptic, hasNativeMainButton } from '@/services/telegram'
import type {
  Language,
  PdfSource,
  PresentationStyle,
  ReferatSize,
  SegmentOption,
  SlideCount,
  WorkType,
} from '@/types'
import { DOC_TYPE_LABELS } from '@/utils/format'

const store = useAppStore()
const form = store.form

const slideOptions: SegmentOption<SlideCount>[] = [
  { value: 8, label: '8 ta' },
  { value: 10, label: '10 ta' },
  { value: 15, label: '15 ta' },
]

const languageOptions: SegmentOption<Language>[] = [
  { value: 'uz', label: 'O‘zbekcha' },
  { value: 'ru', label: 'Русский' },
  { value: 'en', label: 'English' },
]

const styleOptions: SegmentOption<PresentationStyle>[] = [
  { value: 'business', label: 'Biznes', hint: 'Zamonaviy' },
  { value: 'academic', label: 'Akademik', hint: 'Ilmiy' },
  { value: 'creative', label: 'Kreativ', hint: 'Minimal' },
]

const sizeOptions: SegmentOption<ReferatSize>[] = [
  { value: 'short', label: 'Qisqa', hint: '5–7 bet' },
  { value: 'standard', label: 'Standart', hint: '10–12 bet' },
]

const workTypeOptions: SegmentOption<WorkType>[] = [
  { value: 'referat', label: 'Referat' },
  { value: 'mustaqil', label: 'Mustaqil ish' },
]

const titleFields: { key: 'institution' | 'student' | 'teacher'; placeholder: string; max: number }[] = [
  { key: 'institution', placeholder: 'Muassasa nomi (masalan: TDIU)', max: 200 },
  { key: 'student', placeholder: 'Bajardi: talaba F.I.Sh., guruh', max: 120 },
  { key: 'teacher', placeholder: 'Qabul qildi: o‘qituvchi F.I.Sh.', max: 120 },
]

const sourceOptions: SegmentOption<PdfSource>[] = [
  { value: 'presentation', label: 'Slayd' },
  { value: 'referat', label: 'Referat' },
]

const SUGGESTIONS: Record<'presentation' | 'referat', string[]> = {
  presentation: [
    'O‘zbekistonda raqamli iqtisodiyot',
    'Sun’iy intellekt va ta’lim',
    'Yashil energetika istiqbollari',
  ],
  referat: [
    'Amir Temur davlatchiligi',
    'Globallashuv va milliy iqtisodiyot',
    'Ekologik muammolar va yechimlar',
  ],
}

const showPresentationOptions = computed(
  () => store.docType === 'presentation' || (store.docType === 'pdf' && form.source === 'presentation'),
)
const showReferatOptions = computed(
  () => store.docType === 'referat' || (store.docType === 'pdf' && form.source === 'referat'),
)
const suggestions = computed(() => SUGGESTIONS[showReferatOptions.value ? 'referat' : 'presentation'])

const heading = computed(() => DOC_TYPE_LABELS[store.docType])
const headerIcon = computed(() =>
  store.docType === 'presentation' ? Presentation : store.docType === 'referat' ? FileText : FileDown,
)
const outputHint = computed(() => {
  if (store.docType === 'presentation') return 'PowerPoint (.pptx) + PDF'
  if (store.docType === 'referat') return 'Word (.docx) + PDF'
  return 'PDF (.pdf)'
})

const topicLength = computed(() => form.topic.trim().length)
const topicError = computed(() => topicLength.value > 0 && topicLength.value < TOPIC_MIN)

const showExtra = ref(false)

function useSuggestion(text: string): void {
  haptic.select()
  form.topic = text
}

function toggleExtra(): void {
  haptic.select()
  showExtra.value = !showExtra.value
}
</script>

<template>
  <form class="space-y-6" novalidate @submit.prevent="store.generate()">
    <!-- Telegram provides a native BackButton; regular browsers get this one -->
    <button
      v-if="!hasNativeMainButton"
      type="button"
      class="pressable -mb-2 flex items-center gap-1 px-1 text-[15px] font-medium text-app-link"
      @click="store.goHome()"
    >
      <ChevronLeft class="size-5" />
      Orqaga
    </button>

    <!-- Title -->
    <div class="flex items-center gap-3 px-1">
      <span class="bg-brand-gradient flex size-11 items-center justify-center rounded-2xl text-white shadow-lg shadow-brand-violet/25">
        <component :is="headerIcon" class="size-6" :stroke-width="1.8" />
      </span>
      <div>
        <h1 class="text-[22px] leading-tight font-bold">{{ heading }}</h1>
        <p class="text-[13px] text-app-hint">Natija: {{ outputHint }}</p>
      </div>
    </div>

    <!-- Topic -->
    <div class="space-y-2">
      <label for="topic" class="block px-1 text-[13px] font-medium tracking-wide text-app-hint uppercase">
        Mavzuni kiriting
      </label>
      <div
        class="rounded-2xl bg-app-card ring-1 transition-shadow focus-within:ring-2"
        :class="topicError ? 'ring-app-danger/60' : 'ring-app-border focus-within:ring-brand-blue/60'"
      >
        <textarea
          id="topic"
          v-model="form.topic"
          rows="3"
          :maxlength="TOPIC_MAX"
          placeholder="Masalan: O‘zbekistonda raqamli iqtisodiyot"
          class="block w-full resize-none rounded-2xl bg-transparent px-4 pt-3.5 pb-1 text-[16px] leading-snug text-app-text outline-none placeholder:text-app-hint/70"
          enterkeyhint="done"
          @keydown.enter.exact.prevent="($event.target as HTMLTextAreaElement).blur()"
        />
        <div class="flex items-center justify-between px-4 pb-2.5 text-[12px]">
          <span :class="topicError ? 'text-app-danger' : 'text-app-hint'">
            {{ topicError ? `Kamida ${TOPIC_MIN} ta belgi` : 'Aniq va qisqa mavzu yaxshi natija beradi' }}
          </span>
          <span class="text-app-hint tabular-nums">{{ topicLength }}/{{ TOPIC_MAX }}</span>
        </div>
      </div>

      <div v-if="!form.topic" class="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
        <button
          v-for="s in suggestions"
          :key="s"
          type="button"
          class="pressable flex shrink-0 items-center gap-1.5 rounded-full bg-app-card px-3 py-1.5 text-[13px] text-app-text ring-1 ring-app-border"
          @click="useSuggestion(s)"
        >
          <Lightbulb class="size-3.5 text-amber-500" />
          {{ s }}
        </button>
      </div>
    </div>

    <!-- PDF source -->
    <SegmentedControl v-if="store.docType === 'pdf'" v-model="form.source" :options="sourceOptions" label="PDF asosi" />

    <!-- Presentation options -->
    <template v-if="showPresentationOptions">
      <SegmentedControl v-model="form.slides" :options="slideOptions" label="Slaydlar soni" />
      <SegmentedControl v-model="form.style" :options="styleOptions" label="Uslub" />
    </template>

    <!-- Referat options -->
    <template v-if="showReferatOptions">
      <SegmentedControl v-model="form.workType" :options="workTypeOptions" label="Ish turi" />
      <SegmentedControl v-model="form.size" :options="sizeOptions" label="Hajmi" />
    </template>

    <SegmentedControl v-model="form.language" :options="languageOptions" label="Til" />

    <!-- Optional title-page details -->
    <div v-if="store.docType === 'referat'" class="overflow-hidden rounded-2xl bg-app-card ring-1 ring-app-border">
      <button
        type="button"
        class="flex w-full items-center justify-between px-4 py-3.5 text-left"
        :aria-expanded="showExtra"
        @click="toggleExtra"
      >
        <span>
          <span class="block text-[15px] font-medium">Titul varag‘i ma’lumotlari</span>
          <span class="block text-[12px] text-app-hint">Ixtiyoriy: muassasa, talaba va o‘qituvchi</span>
        </span>
        <ChevronDown class="size-5 text-app-hint transition-transform" :class="showExtra && 'rotate-180'" />
      </button>
      <div v-if="showExtra" class="space-y-3 px-4 pb-4">
        <input
          v-for="field in titleFields"
          :key="field.key"
          v-model="form[field.key]"
          type="text"
          :maxlength="field.max"
          :placeholder="field.placeholder"
          class="w-full rounded-xl bg-app-text/[0.05] px-3.5 py-3 text-app-text outline-none placeholder:text-app-hint/70 focus:ring-2 focus:ring-brand-blue/50"
        />
      </div>
    </div>

    <p class="px-1 text-center text-[12px] text-app-hint">
      1 ta hujjat = 1 ta generatsiya. Tayyorlash 1–3 daqiqa davom etadi.
    </p>

    <!-- In-page button for regular browsers (Telegram shows its native MainButton instead) -->
    <div v-if="!hasNativeMainButton" class="sticky bottom-0 -mx-4 bg-gradient-to-t from-app-bg via-app-bg to-transparent px-4 pt-6 pb-safe">
      <button
        type="submit"
        class="pressable bg-brand-gradient flex h-14 w-full items-center justify-center gap-2 rounded-2xl text-[17px] font-semibold text-white shadow-xl shadow-brand-blue/30 disabled:opacity-50"
        :disabled="!store.topicValid || store.submitting"
      >
        <Loader2 v-if="store.submitting" class="size-5 animate-spin" />
        <template v-else>
          Generatsiya qilish
          <Rocket class="size-5" />
        </template>
      </button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, CircleAlert, Download, Info, Loader2, PartyPopper, Send } from 'lucide-vue-next'
import BottomSheet from './ui/BottomSheet.vue'
import type { DocType, GeneratedFile, Job, JobStage } from '@/types'
import { FORMAT_LABELS, formatSize } from '@/utils/format'

const props = defineProps<{
  open: boolean
  job: Job | null
  docType: DocType
}>()

const emit = defineEmits<{
  close: []
  download: [file: GeneratedFile]
  send: [file: GeneratedFile]
}>()

type StepKey = Exclude<JobStage, 'queued' | 'done'>

const steps = computed<{ key: StepKey; label: string }[]>(() => {
  const ext = props.docType === 'presentation' ? '.pptx' : props.docType === 'referat' ? '.docx' : '.pdf'
  const writing = props.docType === 'presentation' ? 'Matnlar va slaydlar yozilmoqda...' : 'Bo‘limlar va matn yozilmoqda...'
  return [
    { key: 'outline', label: 'Reja tuzilmoqda...' },
    { key: 'writing', label: writing },
    { key: 'rendering', label: `Fayl shakllantirilmoqda (${ext})...` },
  ]
})

const STAGE_ORDER: JobStage[] = ['queued', 'outline', 'writing', 'rendering', 'done']

function stepState(key: StepKey): 'done' | 'active' | 'todo' {
  const job = props.job
  if (!job) return 'todo'
  if (job.status === 'completed') return 'done'
  const current = STAGE_ORDER.indexOf(job.stage)
  const target = STAGE_ORDER.indexOf(key)
  if (current > target) return 'done'
  if (current === target) return job.status === 'failed' ? 'todo' : 'active'
  return 'todo'
}

const status = computed(() => props.job?.status ?? 'pending')
const isRunning = computed(() => status.value === 'pending' || status.value === 'running')
const progress = computed(() => Math.min(100, Math.max(0, props.job?.progress ?? 0)))

/** Primary file first (pptx/docx), PDF second. */
const files = computed(() =>
  [...(props.job?.files ?? [])].sort((a, b) => (a.format === 'pdf' ? 1 : 0) - (b.format === 'pdf' ? 1 : 0)),
)
</script>

<template>
  <BottomSheet :open="open" :dismissible="!isRunning" labelledby="progress-title" @close="emit('close')">
    <!-- Running -->
    <div v-if="isRunning" class="pt-2 pb-2">
      <div class="mb-6 flex flex-col items-center text-center">
        <div class="relative mb-4 flex size-20 items-center justify-center">
          <span class="bg-brand-gradient absolute inset-0 animate-ping rounded-full opacity-20" />
          <span class="bg-brand-gradient relative flex size-16 items-center justify-center rounded-full text-white shadow-xl shadow-brand-violet/30">
            <Loader2 class="size-8 animate-spin" />
          </span>
        </div>
        <h2 id="progress-title" class="text-[20px] font-bold">Hujjat tayyorlanmoqda</h2>
        <p class="mt-1 text-[14px] text-app-hint">Ilovani yopmang — bu 1–3 daqiqa oladi</p>
      </div>

      <div class="mb-6">
        <div class="mb-2 flex justify-between text-[13px]">
          <span class="text-app-hint">Jarayon</span>
          <span class="font-semibold tabular-nums">{{ progress }}%</span>
        </div>
        <div class="relative h-2.5 overflow-hidden rounded-full bg-app-text/[0.08]">
          <div
            class="bg-brand-gradient relative h-full overflow-hidden rounded-full transition-[width] duration-700 ease-out"
            :style="{ width: `${Math.max(progress, 4)}%` }"
          >
            <span class="animate-shimmer absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent" />
          </div>
        </div>
      </div>

      <ol class="mb-4 space-y-1">
        <li
          v-for="step in steps"
          :key="step.key"
          class="flex items-center gap-3 rounded-2xl px-3 py-2.5 transition-colors"
          :class="stepState(step.key) === 'active' && 'bg-brand-blue/[0.07]'"
        >
          <span
            class="flex size-7 shrink-0 items-center justify-center rounded-full transition-colors"
            :class="{
              'bg-emerald-500 text-white': stepState(step.key) === 'done',
              'bg-brand-blue text-white': stepState(step.key) === 'active',
              'bg-app-text/[0.08] text-app-hint': stepState(step.key) === 'todo',
            }"
          >
            <Check v-if="stepState(step.key) === 'done'" class="size-4" :stroke-width="3" />
            <Loader2 v-else-if="stepState(step.key) === 'active'" class="size-4 animate-spin" />
            <span v-else class="size-1.5 rounded-full bg-current" />
          </span>
          <span
            class="text-[15px]"
            :class="stepState(step.key) === 'todo' ? 'text-app-hint' : 'font-medium text-app-text'"
          >
            {{ step.label }}
          </span>
        </li>
      </ol>
    </div>

    <!-- Completed -->
    <div v-else-if="status === 'completed'" class="pt-2 pb-2">
      <div class="mb-6 flex flex-col items-center text-center">
        <span class="mb-4 flex size-16 items-center justify-center rounded-full bg-emerald-500 text-white shadow-xl shadow-emerald-500/30">
          <PartyPopper class="size-8" />
        </span>
        <h2 id="progress-title" class="text-[20px] font-bold">Hujjat tayyor!</h2>
        <p class="mt-1 text-[14px] text-app-hint">Yuklab oling yoki Telegram chatga yuboring</p>
      </div>

      <div class="space-y-3">
        <div v-for="(file, i) in files" :key="file.id" class="space-y-2">
          <button
            type="button"
            class="pressable flex h-14 w-full items-center justify-center gap-2 rounded-2xl text-[16px] font-semibold"
            :class="
              i === 0
                ? 'bg-brand-gradient text-white shadow-xl shadow-brand-blue/30'
                : 'bg-app-text/[0.06] text-app-text'
            "
            @click="emit('download', file)"
          >
            <Download class="size-5" />
            Yuklab olish (.{{ file.format }})
            <span class="text-[12px] font-normal opacity-70">· {{ formatSize(file.sizeBytes) }}</span>
          </button>
        </div>

        <button
          v-if="files.length"
          type="button"
          class="pressable flex h-12 w-full items-center justify-center gap-2 rounded-2xl text-[15px] font-semibold text-app-link ring-1 ring-app-border"
          @click="files.forEach((f) => emit('send', f))"
        >
          <Send class="size-4" />
          Telegram chatga yuborish
          <span class="text-[12px] font-normal text-app-hint">({{ files.map((f) => FORMAT_LABELS[f.format]).join(' + ') }})</span>
        </button>
      </div>

      <p
        v-if="job?.isFree"
        class="mt-4 flex items-start gap-2 rounded-2xl bg-amber-500/10 px-3 py-2.5 text-[12px] leading-snug text-amber-700 dark:text-amber-300"
      >
        <Info class="mt-0.5 size-4 shrink-0" />
        Bepul urinishda hujjat oxirida “SlideCraft AI” belgisi bo‘ladi. Pullik paketda belgi qo‘yilmaydi.
      </p>

      <button type="button" class="mt-4 w-full py-3 text-[15px] font-medium text-app-hint" @click="emit('close')">
        Yopish
      </button>
    </div>

    <!-- Failed -->
    <div v-else class="pt-2 pb-2 text-center">
      <span class="mx-auto mb-4 flex size-16 items-center justify-center rounded-full bg-app-danger/10 text-app-danger">
        <CircleAlert class="size-8" />
      </span>
      <h2 id="progress-title" class="text-[20px] font-bold">Tayyorlab bo‘lmadi</h2>
      <p class="mx-auto mt-1 max-w-xs text-[14px] text-app-hint">
        {{ job?.error || 'Kutilmagan xatolik yuz berdi.' }}
      </p>
      <p class="mx-auto mt-3 max-w-xs text-[13px] text-app-hint">Generatsiya hisobingizdan yechilmadi.</p>
      <button
        type="button"
        class="pressable mt-6 h-12 w-full rounded-2xl bg-app-text/[0.06] text-[15px] font-semibold"
        @click="emit('close')"
      >
        Tushunarli
      </button>
    </div>
  </BottomSheet>
</template>

<script setup lang="ts">
import type { Component } from 'vue'
import { Download, FileDown, FileText, FolderOpen, Loader2, Presentation, TriangleAlert } from 'lucide-vue-next'
import type { DocType, GeneratedFile, HistoryItem } from '@/types'
import { formatRelativeDate } from '@/utils/format'

defineProps<{
  items: HistoryItem[]
  loading?: boolean
}>()

defineEmits<{ download: [file: GeneratedFile] }>()

const ICONS: Record<DocType, Component> = {
  presentation: Presentation,
  referat: FileText,
  pdf: FileDown,
}
</script>

<template>
  <section aria-labelledby="history-title" class="space-y-3">
    <h2 id="history-title" class="px-1 text-[13px] font-medium tracking-wide text-app-hint uppercase">
      Mening hujjatlarim
    </h2>

    <div class="overflow-hidden rounded-3xl bg-app-card ring-1 ring-app-border">
      <div v-if="loading && !items.length" class="space-y-3 p-4">
        <div v-for="n in 2" :key="n" class="flex items-center gap-3">
          <div class="skeleton size-10 rounded-xl" />
          <div class="flex-1 space-y-2">
            <div class="skeleton h-3.5 w-3/4 rounded" />
            <div class="skeleton h-3 w-1/3 rounded" />
          </div>
        </div>
      </div>

      <div v-else-if="!items.length" class="flex flex-col items-center px-6 py-8 text-center">
        <span class="mb-3 flex size-12 items-center justify-center rounded-2xl bg-app-text/[0.05]">
          <FolderOpen class="size-6 text-app-hint" />
        </span>
        <p class="text-[15px] font-medium">Hali hujjatlar yo‘q</p>
        <p class="mt-1 text-[13px] text-app-hint">Birinchi hujjatingizni yuqoridan tanlab yarating</p>
      </div>

      <ul v-else class="divide-y divide-app-border">
        <li v-for="item in items" :key="item.id" class="flex items-center gap-3 px-4 py-3">
          <span
            class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-blue/10 text-brand-blue dark:text-blue-300"
          >
            <component :is="ICONS[item.type]" class="size-5" />
          </span>

          <div class="min-w-0 flex-1">
            <p class="truncate text-[15px] font-medium">{{ item.topic }}</p>
            <p class="flex items-center gap-1 text-[12px] text-app-hint">
              <template v-if="item.status === 'completed'">{{ formatRelativeDate(item.createdAt) }}</template>
              <template v-else-if="item.status === 'failed'">
                <TriangleAlert class="size-3 text-app-danger" /> Xatolik
              </template>
              <template v-else> <Loader2 class="size-3 animate-spin" /> Tayyorlanmoqda </template>
            </p>
          </div>

          <div v-if="item.status === 'completed'" class="flex shrink-0 gap-1.5">
            <button
              v-for="file in item.files"
              :key="file.id"
              type="button"
              class="pressable flex items-center gap-1 rounded-xl bg-app-text/[0.06] px-2.5 py-1.5 text-[12px] font-semibold text-app-text uppercase"
              :aria-label="`${file.name} yuklab olish`"
              @click="$emit('download', file)"
            >
              <Download class="size-3.5" />
              {{ file.format }}
            </button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>

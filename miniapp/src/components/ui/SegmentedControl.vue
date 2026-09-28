<script setup lang="ts" generic="T extends string | number">
import { computed } from 'vue'
import { haptic } from '@/services/telegram'
import type { SegmentOption } from '@/types'

const props = defineProps<{
  options: SegmentOption<T>[]
  label?: string
}>()

const model = defineModel<T>({ required: true })

const activeIndex = computed(() => Math.max(0, props.options.findIndex((o) => o.value === model.value)))

function select(value: T): void {
  if (value === model.value) return
  haptic.select()
  model.value = value
}
</script>

<template>
  <fieldset class="space-y-2">
    <legend v-if="label" class="mb-2 px-1 text-[13px] font-medium tracking-wide text-app-hint uppercase">
      {{ label }}
    </legend>
    <div
      class="relative grid rounded-2xl bg-app-text/[0.06] p-1"
      :style="{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }"
      role="radiogroup"
    >
      <span
        class="absolute top-1 bottom-1 left-1 rounded-xl bg-app-card shadow-sm ring-1 ring-app-border transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]"
        :style="{
          width: `calc((100% - 0.5rem) / ${options.length})`,
          transform: `translateX(${activeIndex * 100}%)`,
        }"
        aria-hidden="true"
      />
      <button
        v-for="opt in options"
        :key="String(opt.value)"
        type="button"
        role="radio"
        :aria-checked="opt.value === model"
        class="relative z-10 flex min-h-11 flex-col items-center justify-center rounded-xl px-2 py-1.5 text-center transition-colors"
        :class="opt.value === model ? 'text-app-text' : 'text-app-hint'"
        @click="select(opt.value)"
      >
        <span class="text-[15px] leading-tight font-semibold">{{ opt.label }}</span>
        <span v-if="opt.hint" class="mt-0.5 text-[11px] leading-tight opacity-80">{{ opt.hint }}</span>
      </button>
    </div>
  </fieldset>
</template>

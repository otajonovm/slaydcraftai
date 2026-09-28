<script setup lang="ts">
import { watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    /** When false, tapping the backdrop does nothing (e.g. while a job is running). */
    dismissible?: boolean
    labelledby?: string
  }>(),
  { dismissible: true, labelledby: undefined },
)

const emit = defineEmits<{ close: [] }>()

function onBackdrop(): void {
  if (props.dismissible) emit('close')
}

watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? 'hidden' : ''
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]" @click="onBackdrop" />
    </Transition>
    <Transition name="sheet">
      <div
        v-if="open"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="labelledby"
        class="fixed inset-x-0 bottom-0 z-50 mx-auto max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-[28px] bg-app-card pb-safe shadow-[0_-12px_40px_rgba(15,23,42,0.18)]"
      >
        <div class="sticky top-0 z-10 flex justify-center bg-app-card pt-2.5 pb-1.5">
          <span class="h-1.5 w-10 rounded-full bg-app-hint/30" />
        </div>
        <div class="px-5">
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

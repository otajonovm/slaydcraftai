<script setup lang="ts">
import { computed, ref } from 'vue'
import { BadgeCheck, ChevronRight, Sparkles } from 'lucide-vue-next'
import type { Balance, User } from '@/types'
import { describeBalance } from '@/utils/format'

const props = defineProps<{
  user: User | null
  balance: Balance | null
  loading?: boolean
}>()

defineEmits<{ 'open-tariffs': [] }>()

const avatarFailed = ref(false)

const fullName = computed(() => {
  if (!props.user) return ''
  return [props.user.firstName, props.user.lastName].filter(Boolean).join(' ')
})

const initials = computed(() => {
  if (!props.user) return '?'
  const a = props.user.firstName.charAt(0)
  const b = props.user.lastName?.charAt(0) ?? ''
  return (a + b).toUpperCase() || '?'
})

const balanceText = computed(() => (props.balance ? describeBalance(props.balance) : null))
const isEmpty = computed(() => (props.balance ? props.balance.credits + props.balance.freeCredits <= 0 : false))
</script>

<template>
  <header class="glass flex items-center gap-3 rounded-3xl p-3 shadow-[0_8px_30px_rgba(37,99,235,0.08)]">
    <template v-if="loading || !user">
      <div class="skeleton size-12 shrink-0 rounded-full" />
      <div class="flex-1 space-y-2">
        <div class="skeleton h-4 w-32 rounded-md" />
        <div class="skeleton h-3 w-20 rounded-md" />
      </div>
      <div class="skeleton h-10 w-28 rounded-2xl" />
    </template>

    <template v-else>
      <div class="relative shrink-0">
        <img
          v-if="user.photoUrl && !avatarFailed"
          :src="user.photoUrl"
          :alt="fullName"
          class="size-12 rounded-full object-cover ring-2 ring-white/60 dark:ring-white/10"
          referrerpolicy="no-referrer"
          @error="avatarFailed = true"
        />
        <div
          v-else
          class="bg-brand-gradient flex size-12 items-center justify-center rounded-full text-lg font-semibold text-white"
        >
          {{ initials }}
        </div>
        <span
          v-if="user.isPremium"
          class="absolute -right-0.5 -bottom-0.5 flex size-5 items-center justify-center rounded-full bg-app-card"
          title="Premium"
        >
          <BadgeCheck class="size-4 text-brand-violet" />
        </span>
      </div>

      <div class="min-w-0 flex-1">
        <p class="truncate text-[17px] leading-tight font-semibold">{{ fullName }}</p>
        <p class="truncate text-[13px] text-app-hint">
          {{ user.username ? `@${user.username}` : 'SlideCraft AI' }}
        </p>
      </div>

      <button
        type="button"
        class="pressable flex shrink-0 items-center gap-1.5 rounded-2xl py-2 pr-2 pl-3 text-left"
        :class="isEmpty ? 'bg-app-danger/10 text-app-danger' : 'bg-brand-blue/10 text-brand-blue dark:text-blue-300'"
        :aria-label="`Balans: ${balanceText?.primary}`"
        @click="$emit('open-tariffs')"
      >
        <Sparkles class="size-4 shrink-0" />
        <span class="flex flex-col">
          <span class="text-[14px] leading-tight font-semibold whitespace-nowrap">{{ balanceText?.primary }}</span>
          <span v-if="balanceText?.secondary" class="text-[11px] leading-tight opacity-75">
            {{ balanceText.secondary }}
          </span>
        </span>
        <ChevronRight class="size-4 shrink-0 opacity-60" />
      </button>
    </template>
  </header>
</template>

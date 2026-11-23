<script setup lang="ts">
import type { Transfer } from '@/lib/types'
import { PauseIcon, PlayIcon, RotateCcwIcon, XIcon } from '@lucide/vue'
import { useIntervalFn } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ago, bytes, fullDate, splitPath, speed, stamp } from '@/lib/format'
import { transferState } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'

const props = withDefaults(defineProps<{ transfer: Transfer, actions?: boolean, busy?: boolean, selectable?: boolean, selected?: boolean, peer?: boolean }>(), { actions: true, busy: false, selectable: false, selected: false, peer: true })
const emit = defineEmits<{ cancel: [id: number], retry: [id: number], pause: [id: number], resume: [id: number], select: [id: number, on: boolean] }>()
const { t } = useI18n()
const live = useLive()

/** Merge the stored row with the live progress received over the WebSocket. */
const tr = computed(() => ({ ...props.transfer, ...(live.transfers.get(props.transfer.id) ?? {}) }) as Transfer)
const pct = computed(() => (tr.value.size ? Math.min(100, (tr.value.bytes_transferred / tr.value.size) * 100) : 0))
const name = computed(() => splitPath(tr.value.remote_path).name)
const running = computed(() => ['queued', 'initializing', 'transferring'].includes(tr.value.state))
/** Since when each download has been "connecting" (shared across rows and re-renders) */
const connectingSince = (globalThis as { __slskConnecting?: Map<number, number> }).__slskConnecting ??= new Map()
const now = ref(Date.now())
const ticker = useIntervalFn(() => (now.value = Date.now()), 1000, { immediate: false })
watch(() => tr.value.state, (state) => {
  if (state === 'initializing') {
    if (!connectingSince.has(tr.value.id))
      connectingSince.set(tr.value.id, Date.now())
    now.value = Date.now()
    ticker.resume()
  }
  else {
    connectingSince.delete(tr.value.id)
    ticker.pause()
  }
}, { immediate: true })
const connectingFor = computed(() => {
  const since = connectingSince.get(tr.value.id)
  return since && tr.value.state === 'initializing' ? Math.max(0, Math.round((now.value - since) / 1000)) : null
})

const DOT: Record<string, string> = {
  success: 'bg-success', signal: 'bg-primary', warning: 'bg-warning', danger: 'bg-destructive', quiet: 'border border-faint',
}

/** The bar only says something while the file moves: a finished one has its badge */
const showBar = computed(() => tr.value.state === 'transferring' || ((running.value || tr.value.state === 'paused') && tr.value.bytes_transferred > 0))

/** When it ended, or else when it was asked for */
const when = computed(() => {
  const done = ['complete', 'failed', 'aborted'].includes(tr.value.state) ? tr.value.completed_at : null
  const iso = done ?? tr.value.created_at
  if (!iso)
    return null
  const key = done ? 'transfer.endedAt' : tr.value.direction === 'download' ? 'transfer.requestedAt' : 'transfer.askedAt'
  return { iso, text: stamp(iso), hint: t(key, { date: fullDate(iso) }) }
})

/** Album download that stopped moving: shown first, it's what needs you */
const stuck = computed(() => !!tr.value.stuck && running.value && tr.value.direction === 'download')
const stuckHint = computed(() => stuck.value
  ? t(`transfer.stuckWhy.${tr.value.stuck_reason}`, { since: ago(tr.value.stuck_since), n: tr.value.attempts, place: tr.value.place_in_queue ?? '?' })
  : '')

const st = computed(() => {
  if (stuck.value)
    return { label: t('transfer.stuck'), badge: 'warning' as const }
  // "Queued" alone means nothing: did the peer accept, and where are we in their queue?
  if (tr.value.direction === 'download' && tr.value.state === 'queued') {
    return tr.value.remotely_queued
      ? { label: tr.value.place_in_queue ? t('transfer.inTheirQueueAt', { n: tr.value.place_in_queue }) : t('transfer.inTheirQueue'), badge: 'signal' as const }
      : { label: t('transfer.requested'), badge: 'quiet' as const }
  }
  if (tr.value.direction === 'download' && connectingFor.value !== null && connectingFor.value >= 3)
    return { label: t('transfer.connectingFor', { s: connectingFor.value }), badge: connectingFor.value >= 30 ? 'warning' as const : 'signal' as const }
  return transferState(tr.value.state)
})
</script>

<template>
  <!-- One line per file: the album and the peer are in the card around it -->
  <div :class="cn('group py-2', selected && '-mx-4 bg-primary/[0.06] px-4')">
    <div class="flex min-h-6 items-center gap-3">
      <Checkbox
        v-if="selectable"
        :model-value="selected"
        :aria-label="t('folder.select', { name })"
        @update:model-value="(v) => emit('select', tr.id, v === true)"
      />
      <span class="min-w-0 flex-1 truncate text-[13px] text-foreground" :title="tr.local_path ?? tr.remote_path">{{ name }}</span>
      <RouterLink
        v-if="peer"
        :to="{ name: 'peer', params: { username: tr.username } }"
        class="hidden max-w-40 truncate font-mono text-[11.5px] text-faint hover:text-primary sm:inline"
        :title="tr.direction === 'download' ? t('transfer.from') : t('transfer.to')"
      >
        {{ tr.username }}
      </RouterLink>
      <span class="hidden shrink-0 font-mono text-[11px] text-muted-foreground tnum sm:inline">
        <template v-if="tr.state === 'transferring'">{{ speed(tr.speed) }} · </template>
        <template v-if="tr.state === 'complete' || !tr.bytes_transferred">{{ tr.size ? bytes(tr.size) : '' }}</template>
        <template v-else>{{ bytes(tr.bytes_transferred) }}<span class="text-faint"> / {{ bytes(tr.size) }}</span></template>
      </span>
      <Tooltip>
        <TooltipTrigger as-child>
          <span class="inline-flex shrink-0" :aria-label="st.label">
            <!-- Narrow screens: a dot, the file name keeps the room -->
            <span :class="cn('size-2 rounded-full sm:hidden', DOT[st.badge] ?? 'bg-faint')" />
            <Badge :variant="st.badge" class="hidden sm:inline-flex">{{ st.label }}</Badge>
          </span>
        </TooltipTrigger>
        <TooltipContent class="max-w-64">
          <template v-if="stuck">
            {{ stuckHint }} {{ t('transfer.stuckAction') }}
          </template>
          <template v-else-if="tr.state === 'queued' && tr.direction === 'download'">
            {{ tr.remotely_queued
              ? t('transfer.acceptedHint', { peer: tr.username })
              : t('transfer.requestedHint', { peer: tr.username }) }}
          </template>
          <template v-else-if="tr.state === 'initializing' && tr.direction === 'download'">
            {{ t('transfer.connectingHint', { peer: tr.username }) }}
          </template>
          <template v-else>
            {{ st.label }}
          </template>
        </TooltipContent>
      </Tooltip>
      <span v-if="(tr.attempts ?? 1) > 1" class="shrink-0 font-mono text-[10.5px] text-faint tnum" :title="t('transfer.attempts')">{{ t('transfer.attempt', { n: tr.attempts }) }}</span>
      <div v-if="actions" class="flex shrink-0 sm:w-[76px] items-center justify-end gap-0.5">
        <Tooltip v-if="running && tr.direction === 'download'">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-xs" class="text-faint hover:text-foreground" :aria-label="t('common.pause')" :disabled="busy" @click="emit('pause', tr.id)">
              <PauseIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ t('transfer.pauseHint') }}</TooltipContent>
        </Tooltip>
        <Tooltip v-if="tr.state === 'paused'">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-xs" class="text-primary" :aria-label="t('common.resume')" :disabled="busy" @click="emit('resume', tr.id)">
              <PlayIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ t('common.resume') }}</TooltipContent>
        </Tooltip>
        <Tooltip v-if="running || tr.state === 'paused'">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-xs" class="text-faint hover:text-destructive" :aria-label="t('common.cancel')" :disabled="busy" @click="emit('cancel', tr.id)">
              <XIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ t('transfer.cancelHint') }}</TooltipContent>
        </Tooltip>
        <Tooltip v-else-if="tr.direction === 'download' && tr.state !== 'complete'">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-xs" class="text-muted-foreground hover:text-primary" :aria-label="t('common.retry')" :disabled="busy" @click="emit('retry', tr.id)">
              <RotateCcwIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ t('transfer.retryHint') }}</TooltipContent>
        </Tooltip>
      </div>
      <time v-if="when" :datetime="when.iso" :title="when.hint" class="hidden w-24 shrink-0 text-right font-mono text-[11px] text-faint tnum md:block">{{ when.text }}</time>
    </div>
    <div v-if="showBar" :class="cn('mt-1.5 h-[2px] overflow-hidden rounded-full bg-border', selectable && 'ml-7')">
      <div
        :class="cn('h-full rounded-full transition-[width] duration-500', stuck ? 'bg-warning' : 'bg-primary')"
        :style="{ width: `${pct}%` }"
      />
    </div>
    <p
      v-if="tr.error && tr.state !== 'complete'"
      :class="cn('mt-0.5 truncate text-[11.5px]', selectable && 'ml-7', tr.state === 'failed' ? 'text-destructive' : 'text-faint')"
      :title="tr.error"
    >
      {{ tr.error }}
    </p>
  </div>
</template>

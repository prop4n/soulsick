<script setup lang="ts">
import { ShieldCheckIcon } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { speed } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'
import { serverText } from '@/lib/serverText'

/** Sidebar network module: connection LED + throughput meter. */
const { t } = useI18n()
const live = useLive()
const e = computed(() => live.engine)

const state = computed(() => {
  const s = e.value
  if (!s)
    return { label: t('network.starting'), led: 'bg-faint', text: 'text-faint' }
  if (s.connected)
    return { label: t('network.online'), led: 'bg-success shadow-[0_0_6px_var(--success)]', text: 'text-success' }
  if (s.connecting)
    return { label: t('network.connecting'), led: 'bg-primary animate-pulse', text: 'text-primary' }
  if (!s.configured)
    return { label: t('network.notConfigured'), led: 'bg-faint', text: 'text-muted-foreground' }
  return { label: t('network.offline'), led: 'bg-destructive', text: 'text-destructive' }
})

const W = 168
const H = 22
function line(key: 'down' | 'up') {
  const pts = live.speedHistory
  if (pts.length < 2)
    return ''
  const max = Math.max(64 * 1024, ...pts.map(p => Math.max(p.down, p.up)))
  return pts.map((p, i) => {
    const x = (i / 59) * W
    const y = H - 1 - (p[key] / max) * (H - 2)
    return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}
</script>

<template>
  <div class="flex flex-col gap-2.5 rounded-md border bg-well/60 p-3">
    <div class="flex items-center justify-between gap-2">
      <div class="flex min-w-0 items-center gap-2">
        <span :class="cn('size-[7px] shrink-0 rounded-full', state.led)" />
        <span :class="cn('text-[12px] font-medium', state.text)">{{ state.label }}</span>
      </div>
      <span v-if="e?.username" class="truncate font-mono text-[11px] text-faint">{{ e.username }}</span>
    </div>

    <svg :viewBox="`0 0 ${W} ${H}`" class="h-[22px] w-full" preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" :y1="H - 0.5" :x2="W" :y2="H - 0.5" class="stroke-border-strong" stroke-width="1" />
      <path :d="line('up')" fill="none" class="stroke-muted-foreground/60" stroke-width="1.25" vector-effect="non-scaling-stroke" />
      <path :d="line('down')" fill="none" class="stroke-primary" stroke-width="1.5" vector-effect="non-scaling-stroke" />
    </svg>

    <dl class="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
      <div class="flex flex-col">
        <dt class="legend !text-[9.5px]">
          <span class="text-primary">↓</span> {{ t('network.down') }}
        </dt>
        <dd class="font-mono text-foreground tnum">
          {{ speed(e?.download_speed) }}
        </dd>
      </div>
      <div class="flex flex-col">
        <dt class="legend !text-[9.5px]">
          ↑ {{ t('network.up') }}
        </dt>
        <dd class="font-mono text-foreground tnum">
          {{ speed(e?.upload_speed) }}
        </dd>
      </div>
      <div v-if="e?.forwarded_port" class="col-span-2 flex items-center justify-between pt-1 text-faint" :title="t('network.vpnHint')">
        <span class="flex items-center gap-1.5"><ShieldCheckIcon class="size-3 text-success" />{{ t('network.vpn') }}</span>
        <span class="font-mono tnum text-muted-foreground">{{ t('network.port', { port: e.forwarded_port }) }}</span>
      </div>
      <div class="col-span-2 flex items-center justify-between pt-1 text-faint">
        <span>{{ t('network.uploadSlots') }}</span>
        <span class="font-mono tnum text-muted-foreground">{{ e ? `${e.upload_slots - e.free_upload_slots}/${e.upload_slots}` : '—' }}</span>
      </div>
    </dl>
    <p v-if="e?.error && !e.connected" class="text-[11px] leading-snug text-destructive/90 text-pretty">
      {{ serverText(e.error, e.error_t) }}
    </p>
  </div>
</template>

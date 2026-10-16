<script setup lang="ts">
import { computed } from 'vue'
import { speed } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'

/** Module « réseau » de la barre latérale : voyant de connexion + VU-mètre des débits. */
const live = useLive()
const e = computed(() => live.engine)

const state = computed(() => {
  const s = e.value
  if (!s)
    return { label: 'Initialisation', led: 'bg-faint', text: 'text-faint' }
  if (s.connected)
    return { label: 'En ligne', led: 'bg-success', text: 'text-success' }
  if (s.connecting)
    return { label: 'Connexion…', led: 'bg-primary animate-pulse', text: 'text-primary' }
  if (!s.configured)
    return { label: 'Non configuré', led: 'bg-faint', text: 'text-muted-foreground' }
  return { label: 'Hors ligne', led: 'bg-destructive', text: 'text-destructive' }
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
          <span class="text-primary">↓</span> Réception
        </dt>
        <dd class="font-mono text-foreground tnum">
          {{ speed(e?.download_speed) }}
        </dd>
      </div>
      <div class="flex flex-col">
        <dt class="legend !text-[9.5px]">
          ↑ Envoi
        </dt>
        <dd class="font-mono text-foreground tnum">
          {{ speed(e?.upload_speed) }}
        </dd>
      </div>
      <div class="col-span-2 flex items-center justify-between pt-1 text-faint">
        <span>Slots d’envoi</span>
        <span class="font-mono tnum text-muted-foreground">{{ e ? `${e.upload_slots - e.free_upload_slots}/${e.upload_slots}` : '—' }}</span>
      </div>
    </dl>
    <p v-if="e?.error && !e.connected" class="text-[11px] leading-snug text-destructive/90 text-pretty">
      {{ e.error }}
    </p>
  </div>
</template>

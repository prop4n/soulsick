<script setup lang="ts">
import type { Coverage, CoverageFiller } from '@/lib/types'
import { TriangleAlertIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { speed } from '@/lib/format'
import { FORMAT_LABELS } from '@/lib/status'
import { cn } from '@/lib/utils'
import FormatTag from './FormatTag.vue'

/**
 * Received tracks at a glance (one segment per track) and, when some are
 * missing, which peers can complete the album (manual mixing).
 * The per-track detail lives in the album's Tracks tab.
 */
const props = defineProps<{ albumId: number, coverage: Coverage }>()
const emit = defineEmits<{ details: [] }>()
const { t } = useI18n()
const qc = useQueryClient()

const s = computed(() => props.coverage.summary)
const done = computed(() => s.value.received + s.value.in_library)
const missing = computed(() => props.coverage.tracks.filter(x => x.state === 'missing'))

function segment(state: string, upgrade?: boolean) {
  if (upgrade)
    return 'bg-warning/70'
  return {
    received: 'bg-success',
    in_library: 'bg-success/50',
    downloading: 'bg-primary animate-[pulse_1.6s_ease-in-out_infinite]',
    paused: 'bg-muted-foreground/50',
    missing: 'bg-border-strong',
  }[state]
}

const receivedLabel = computed(() => (props.coverage.received_formats ?? []).map(f => FORMAT_LABELS[f] ?? f).join(', '))

function mixed(f: CoverageFiller) {
  const got = props.coverage.received_formats ?? []
  return !!f.format && got.length > 0 && !got.includes(f.format)
}

const pending = ref<number | null>(null)
const take = useMutation({
  mutationFn: (f: CoverageFiller) => {
    pending.value = f.candidate_id
    return api.post<{ files: number }>(`/albums/${props.albumId}/complete`, {
      candidate_id: f.candidate_id,
      track_ids: f.tracks.map(x => x.track_id),
    })
  },
  onSuccess: (d, f) => {
    toast.success(t('coverage.requested', { n: d.files, peer: f.username }, d.files), { description: t('coverage.requestedHint') })
    qc.invalidateQueries({ queryKey: ['album'] })
  },
  onError: e => toast.error(e.message),
  onSettled: () => (pending.value = null),
})
</script>

<template>
  <section class="flex flex-col gap-4 rounded-xl bg-card/70 p-5 ring-1 ring-white/[0.03] backdrop-blur-xl">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div class="flex flex-col gap-1">
        <span class="legend">{{ t('coverage.title') }}</span>
        <div class="flex items-baseline gap-2">
          <span class="font-mono text-[28px] leading-none font-medium tnum">{{ done }}<span class="text-faint">/{{ s.total }}</span></span>
          <span class="text-[12.5px] text-muted-foreground">
            <template v-if="s.downloading">{{ t('coverage.downloading', { n: s.downloading }) }}</template>
            <template v-if="s.paused">{{ s.downloading ? ' · ' : '' }}{{ t('coverage.paused', { n: s.paused }) }}</template>
            <template v-if="(s.downloading || s.paused) && s.missing"> · </template>
            <span v-if="s.missing" class="text-warning">{{ t('coverage.missing', s.missing) }}</span>
            <template v-if="!s.downloading && !s.paused && !s.missing">{{ t('coverage.complete') }}</template>
          </span>
        </div>
      </div>
      <button type="button" class="text-left text-[11.5px] text-faint hover:text-primary" @click="emit('details')">
        {{ t('coverage.edition', { title: coverage.release_title }) }} · {{ t('coverage.perTrack') }}
      </button>
    </div>

    <!-- One segment per track: the chain, at track scale -->
    <div class="flex gap-[3px]">
      <Tooltip v-for="x in coverage.tracks" :key="x.track_id">
        <TooltipTrigger as-child>
          <span :class="cn('h-1.5 flex-1 rounded-[1px]', segment(x.state, x.upgrade))" />
        </TooltipTrigger>
        <TooltipContent>
          {{ String(x.position).padStart(2, '0') }} · {{ x.title }} — {{ t(`coverage.state.${x.state}`) }}<template v-if="x.upgrade">
            · {{ FORMAT_LABELS[x.library_format ?? ''] ?? x.library_format }}
          </template>
        </TooltipContent>
      </Tooltip>
    </div>

    <!-- Upgrade: tracks below the rest of the album (e.g. an MP3 among FLACs), one file each -->
    <div v-if="s.upgrade && !s.downloading" class="flex flex-col gap-3 border-t pt-4">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-[13.5px] font-semibold">
          {{ t('coverage.upgradeTitle', s.upgrade) }}
        </h3>
        <p class="text-[12px] text-muted-foreground">
          {{ t('coverage.upgradeHint') }}
        </p>
      </div>
      <p v-if="!coverage.upgraders?.length" class="text-[12px] text-faint">
        {{ t('coverage.noUpgrader') }}
      </p>
      <div
        v-for="f in coverage.upgraders ?? []"
        :key="f.candidate_id"
        class="flex flex-col gap-2 rounded-md border px-3 py-2.5 sm:flex-row sm:items-center"
      >
        <div class="flex min-w-0 flex-1 flex-col gap-1">
          <div class="flex items-center gap-2">
            <RouterLink :to="{ name: 'peer', params: { username: f.username } }" class="font-mono text-[12.5px] font-medium hover:text-primary">
              {{ f.username }}
            </RouterLink>
            <span :class="cn('text-[11px]', f.has_free_slots ? 'text-success' : 'text-faint')">{{ f.has_free_slots ? t('peer.freeSlot') : t('peer.queue', { n: f.queue_size }) }}</span>
            <span class="font-mono text-[11px] text-faint tnum">{{ speed(f.avg_speed) }}</span>
          </div>
          <p v-for="x in f.tracks" :key="x.track_id" class="flex items-center gap-1.5 truncate text-[12px] text-muted-foreground">
            {{ x.title }} :
            <span class="font-mono text-[11px] text-warning">{{ FORMAT_LABELS[x.from_format ?? ''] ?? x.from_format }}</span>
            →
            <FormatTag :format="x.format" />
          </p>
        </div>
        <Button size="sm" :disabled="take.isPending.value" @click="take.mutate(f)">
          <Spinner v-if="pending === f.candidate_id" data-icon="inline-start" />
          {{ t('coverage.replace', f.tracks.length) }}
        </Button>
      </div>
    </div>

    <!-- Mixing: who has the missing tracks? -->
    <div v-if="missing.length && !s.downloading" class="flex flex-col gap-3 border-t pt-4">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-[13.5px] font-semibold">
          {{ t('coverage.completeFrom') }}
        </h3>
        <p class="text-[12px] text-muted-foreground">
          {{ t('coverage.completeFromHint') }}
        </p>
      </div>
      <p v-if="!coverage.fillers.length" class="text-[12px] text-faint">
        {{ t('coverage.noFiller') }}
      </p>
      <div
        v-for="f in coverage.fillers"
        :key="f.candidate_id"
        class="flex flex-col gap-2 rounded-md border px-3 py-2.5 sm:flex-row sm:items-center"
      >
        <div class="flex min-w-0 flex-1 flex-col gap-1">
          <div class="flex items-center gap-2">
            <RouterLink :to="{ name: 'peer', params: { username: f.username } }" class="font-mono text-[12.5px] font-medium hover:text-primary">
              {{ f.username }}
            </RouterLink>
            <FormatTag :format="f.format" />
            <span class="font-mono text-[11px] text-faint tnum">{{ Math.round(f.score) }}/100</span>
            <span :class="cn('text-[11px]', f.has_free_slots ? 'text-success' : 'text-faint')">{{ f.has_free_slots ? t('peer.freeSlot') : t('peer.queue', { n: f.queue_size }) }}</span>
            <span class="font-mono text-[11px] text-faint tnum">{{ speed(f.avg_speed) }}</span>
          </div>
          <p class="truncate text-[12px] text-muted-foreground">
            {{ t('coverage.has', { n: f.tracks.length, total: missing.length }) }} {{ f.tracks.map(x => x.title).join(', ') }}
          </p>
          <p v-if="mixed(f)" class="flex items-center gap-1.5 text-[11.5px] text-warning">
            <TriangleAlertIcon class="size-3.5" />
            {{ t('coverage.mixed', { formats: receivedLabel }) }}
          </p>
        </div>
        <Button size="sm" :variant="mixed(f) ? 'outline' : 'default'" :disabled="take.isPending.value" @click="take.mutate(f)">
          <Spinner v-if="pending === f.candidate_id" data-icon="inline-start" />
          {{ t('coverage.take', f.tracks.length) }}
        </Button>
      </div>
    </div>
  </section>
</template>

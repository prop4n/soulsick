<script setup lang="ts">
import type { Coverage, CoverageFiller } from '@/lib/types'
import { TriangleAlertIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { ms, speed } from '@/lib/format'
import { FORMAT_LABELS } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'
import FormatTag from './FormatTag.vue'

/**
 * Couverture piste par piste : d'où vient chaque morceau, ce qui manque,
 * et quels pairs peuvent compléter (panachage manuel).
 */
const props = defineProps<{ albumId: number }>()
const qc = useQueryClient()
const live = useLive()

const { data, isPending } = useQuery({
  queryKey: ['album', computed(() => props.albumId), 'coverage'],
  queryFn: () => api.get<Coverage>(`/albums/${props.albumId}/coverage`),
})

const hasSources = computed(() => !!data.value?.tracks.some(t => t.sources.length))
const s = computed(() => data.value?.summary)
const done = computed(() => (s.value ? s.value.received + s.value.in_library : 0))
const missing = computed(() => data.value?.tracks.filter(t => t.state === 'missing') ?? [])

function segment(state: string) {
  return {
    received: 'bg-success',
    in_library: 'bg-success/50',
    downloading: 'bg-primary animate-[pulse_1.6s_ease-in-out_infinite]',
    missing: 'bg-border-strong',
  }[state]
}

function progress(src: { transfer_id: number, bytes: number, size: number | null }) {
  const l = live.transfers.get(src.transfer_id)
  const bytes = l?.bytes_transferred ?? src.bytes
  const size = l?.size ?? src.size
  return size ? Math.round((bytes / size) * 100) : 0
}

const receivedLabel = computed(() => (data.value?.received_formats ?? []).map(f => FORMAT_LABELS[f] ?? f).join(', '))

function mixed(f: CoverageFiller) {
  const got = data.value?.received_formats ?? []
  return !!f.format && got.length > 0 && !got.includes(f.format)
}

const pending = ref<number | null>(null)
const take = useMutation({
  mutationFn: (f: CoverageFiller) => {
    pending.value = f.candidate_id
    return api.post<{ files: number }>(`/albums/${props.albumId}/complete`, {
      candidate_id: f.candidate_id,
      track_ids: f.tracks.map(t => t.track_id),
    })
  },
  onSuccess: (d, f) => {
    toast.success(`${d.files} piste(s) demandée(s) à ${f.username}`, {
      description: 'Les pistes déjà reçues sont gardées ; l’album sera rangé dès que tout est là.',
    })
    qc.invalidateQueries({ queryKey: ['album'] })
  },
  onError: e => toast.error(e.message),
  onSettled: () => (pending.value = null),
})
</script>

<template>
  <section v-if="isPending" class="flex flex-col gap-2">
    <Skeleton class="h-24 w-full" />
  </section>
  <section v-else-if="data && hasSources" class="flex flex-col gap-4 rounded-lg border bg-card p-5">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div class="flex flex-col gap-1">
        <span class="legend">Pistes reçues</span>
        <div class="flex items-baseline gap-2">
          <span class="font-mono text-[28px] leading-none font-medium tnum">{{ done }}<span class="text-faint">/{{ s?.total }}</span></span>
          <span class="text-[12.5px] text-muted-foreground">
            <template v-if="s?.downloading">{{ s.downloading }} en cours</template>
            <template v-if="s?.downloading && s?.missing"> · </template>
            <span v-if="s?.missing" class="text-warning">{{ s.missing }} manquante(s)</span>
            <template v-if="!s?.downloading && !s?.missing">tout est là</template>
          </span>
        </div>
      </div>
      <span class="text-[11.5px] text-faint">Édition : {{ data.release_title }}</span>
    </div>

    <!-- Une case par piste : la chaîne, à l'échelle du morceau -->
    <div class="flex gap-[3px]">
      <Tooltip v-for="t in data.tracks" :key="t.track_id">
        <TooltipTrigger as-child>
          <span :class="cn('h-1.5 flex-1 rounded-[1px]', segment(t.state))" />
        </TooltipTrigger>
        <TooltipContent>{{ String(t.position).padStart(2, '0') }} · {{ t.title }}</TooltipContent>
      </Tooltip>
    </div>

    <ul class="flex flex-col divide-y divide-border/60">
      <li v-for="t in data.tracks" :key="t.track_id" class="grid grid-cols-[2.25rem_minmax(0,1fr)_auto] items-center gap-3 py-1.5 text-[12.5px]">
        <span class="font-mono text-[11px] text-faint tnum">{{ data.tracks.some(x => x.disc > 1) ? `${t.disc}-` : '' }}{{ String(t.position).padStart(2, '0') }}</span>
        <span :class="cn('truncate', t.state === 'missing' ? 'text-muted-foreground' : 'text-foreground')">
          {{ t.title }} <span class="font-mono text-[11px] text-faint">{{ ms(t.length_ms) }}</span>
        </span>
        <span class="flex items-center justify-end gap-1.5">
          <template v-if="t.sources.length">
            <span
              v-for="src in t.sources.slice(0, 2)"
              :key="src.transfer_id"
              :class="cn('inline-flex items-center gap-1.5 rounded-[4px] border px-1.5 py-px font-mono text-[11px]',
                         src.state === 'complete' ? 'border-success/25 text-success'
                         : ['failed', 'aborted'].includes(src.state) ? 'border-border text-faint line-through'
                           : 'border-primary/30 text-primary')"
            >
              {{ src.username }}
              <span v-if="src.format" class="opacity-70">{{ FORMAT_LABELS[src.format] ?? src.format }}</span>
              <span v-if="src.state === 'transferring'" class="tnum">{{ progress(src) }} %</span>
              <span v-else-if="src.state === 'queued'">en file</span>
            </span>
          </template>
          <span v-else-if="t.state === 'in_library'" class="text-[11px] text-success">déjà dans la bibliothèque</span>
          <span v-else class="text-[11px] text-warning">manquante</span>
        </span>
      </li>
    </ul>

    <!-- Panachage : qui a les pistes manquantes ? -->
    <div v-if="missing.length && !s?.downloading" class="flex flex-col gap-3 border-t pt-4">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-[13.5px] font-semibold">
          Compléter depuis un autre pair
        </h3>
        <p class="text-[12px] text-muted-foreground">
          Seules les pistes manquantes sont téléchargées. À l’import, chaque piste prend le meilleur fichier reçu, et le journal dira d’où vient chacune.
        </p>
      </div>
      <p v-if="!data.fillers.length" class="text-[12px] text-faint">
        Aucun candidat connu n’a ces pistes. Relance une recherche depuis l’en-tête de l’album.
      </p>
      <div
        v-for="f in data.fillers"
        :key="f.candidate_id"
        class="flex flex-col gap-2 rounded-md border px-3 py-2.5 sm:flex-row sm:items-center"
      >
        <div class="flex min-w-0 flex-1 flex-col gap-1">
          <div class="flex items-center gap-2">
            <span class="font-mono text-[12.5px] font-medium">{{ f.username }}</span>
            <FormatTag :format="f.format" />
            <span class="font-mono text-[11px] text-faint tnum">{{ Math.round(f.score) }}/100</span>
            <span :class="cn('text-[11px]', f.has_free_slots ? 'text-success' : 'text-faint')">{{ f.has_free_slots ? 'slot libre' : `file ${f.queue_size}` }}</span>
            <span class="font-mono text-[11px] text-faint tnum">{{ speed(f.avg_speed) }}</span>
          </div>
          <p class="truncate text-[12px] text-muted-foreground">
            A {{ f.tracks.length }}/{{ missing.length }} : {{ f.tracks.map(x => x.title).join(', ') }}
          </p>
          <p v-if="mixed(f)" class="flex items-center gap-1.5 text-[11.5px] text-warning">
            <TriangleAlertIcon class="size-3.5" />
            Format différent de ce qui est déjà reçu ({{ receivedLabel }}) : l’album sera mélangé.
          </p>
        </div>
        <Button size="sm" :variant="mixed(f) ? 'outline' : 'default'" :disabled="take.isPending.value" @click="take.mutate(f)">
          <Spinner v-if="pending === f.candidate_id" data-icon="inline-start" />
          Prendre {{ f.tracks.length }} piste(s)
        </Button>
      </div>
    </div>
  </section>
</template>

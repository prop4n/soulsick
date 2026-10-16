<script setup lang="ts">
import type { PlanItem, Release } from '@/lib/types'
import { TriangleAlertIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'
import { duration, ms } from '@/lib/format'
import { cn } from '@/lib/utils'
import FormatTag from './FormatTag.vue'

/**
 * Revue d'import : rien n'est déplacé tant que tu n'as pas validé l'association
 * fichier → piste. Chaque ligne est modifiable.
 */
const props = defineProps<{ candidateId: number, releases: Release[] }>()
const qc = useQueryClient()

interface PlanResponse {
  plan: PlanItem[]
  info: { confidence: number, release_id: number | null, release_title?: string, unmatched_tracks?: string[], unmatched_files?: string[] }
}

const { data, isPending } = useQuery({
  queryKey: ['plan', computed(() => props.candidateId)],
  queryFn: () => api.get<PlanResponse>(`/candidates/${props.candidateId}/plan`),
})

const releaseId = ref<string>('')
const mapping = ref<Record<string, string>>({})

watch(data, (d) => {
  if (!d)
    return
  releaseId.value = d.info.release_id ? String(d.info.release_id) : String(props.releases[0]?.id ?? '')
  mapping.value = Object.fromEntries(d.plan.map(p => [p.file, p.track_id ? String(p.track_id) : 'skip']))
}, { immediate: true })

const release = computed(() => props.releases.find(r => String(r.id) === releaseId.value))
const used = computed(() => new Set(Object.values(mapping.value).filter(v => v !== 'skip')))
const missing = computed(() => (release.value?.tracks ?? []).filter(t => !used.value.has(String(t.id))))
const duplicates = computed(() => {
  const seen = new Map<string, number>()
  for (const v of Object.values(mapping.value)) {
    if (v !== 'skip')
      seen.set(v, (seen.get(v) ?? 0) + 1)
  }
  return new Set([...seen.entries()].filter(([, n]) => n > 1).map(([k]) => k))
})

watch(releaseId, (_, before) => {
  // Changer d'édition : on réassocie par position quand c'est possible
  if (!before || !release.value || !data.value)
    return
  const byPos = new Map(release.value.tracks.map(t => [`${t.disc}-${t.position}`, String(t.id)]))
  for (const p of data.value.plan)
    mapping.value[p.file] = (p.disc && p.position && byPos.get(`${p.disc}-${p.position}`)) || 'skip'
})

const apply = useMutation({
  mutationFn: () => api.post(`/candidates/${props.candidateId}/import`, {
    release_id: Number(releaseId.value),
    plan: (data.value?.plan ?? []).map(p => ({
      ...p,
      track_id: mapping.value[p.file] === 'skip' ? null : Number(mapping.value[p.file]),
    })),
  }),
  onSuccess: () => {
    toast.success('Import effectué', { description: 'Fichiers tagués, renommés et rangés.' })
    qc.invalidateQueries({ queryKey: ['album'] })
  },
  onError: e => toast.error('Import impossible', { description: e.message }),
})

function trackLabel(id: string) {
  const t = release.value?.tracks.find(x => String(x.id) === id)
  return t ? `${release.value!.disc_count > 1 ? `${t.disc}-` : ''}${String(t.position).padStart(2, '0')} · ${t.title}` : ''
}
</script>

<template>
  <section class="flex flex-col gap-4 rounded-lg border border-warning/30 bg-warning/[0.04] p-5">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div class="flex flex-col gap-1">
        <h2 class="flex items-center gap-2 text-[14px] font-semibold">
          <TriangleAlertIcon class="size-4 text-warning" />
          Vérifie l’import avant rangement
        </h2>
        <p class="max-w-2xl text-[12.5px] text-muted-foreground text-pretty">
          Les fichiers sont dans le dossier de réception, rien n’a été déplacé. Corrige l’association si besoin :
          chaque fichier sera tagué avec les infos MusicBrainz de la piste choisie, renommé, puis rangé.
        </p>
      </div>
      <span v-if="data" class="shrink-0 font-mono text-[11.5px] text-muted-foreground tnum">
        confiance {{ Math.round(data.info.confidence * 100) }} %
      </span>
    </div>

    <div v-if="isPending" class="flex flex-col gap-2">
      <Skeleton v-for="i in 4" :key="i" class="h-9 w-full" />
    </div>

    <template v-else-if="data">
      <div class="flex flex-col gap-1.5">
        <span class="legend">Édition MusicBrainz</span>
        <Select v-model="releaseId">
          <SelectTrigger class="w-full sm:max-w-xl">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem v-for="r in releases" :key="r.id" :value="String(r.id)">
                {{ r.title }} · {{ r.date ?? '?' }} · {{ r.country ?? '?' }} · {{ r.formats || '?' }} · {{ r.track_count }} pistes
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </div>

      <div class="overflow-hidden rounded-md border bg-card">
        <div
          v-for="p in data.plan"
          :key="p.file"
          class="grid items-center gap-x-4 gap-y-1.5 border-b px-3 py-2 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]"
        >
          <div class="flex min-w-0 items-center gap-2">
            <FormatTag :format="p.format" />
            <span class="truncate font-mono text-[12px]" :title="p.file">{{ p.name }}</span>
            <span class="shrink-0 font-mono text-[11px] text-faint tnum">{{ duration(p.duration) }}</span>
          </div>
          <span class="hidden text-faint sm:block">→</span>
          <Select v-model="mapping[p.file]">
            <SelectTrigger
              size="sm"
              :class="cn('w-full', mapping[p.file] === 'skip' && 'text-faint', duplicates.has(mapping[p.file] ?? '') && 'border-destructive/60')"
            >
              <SelectValue>{{ mapping[p.file] === 'skip' ? 'Ne pas importer' : trackLabel(mapping[p.file] ?? '') }}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="skip">
                  Ne pas importer
                </SelectItem>
                <SelectItem v-for="t in release?.tracks ?? []" :key="t.id" :value="String(t.id)">
                  {{ release!.disc_count > 1 ? `${t.disc}-` : '' }}{{ String(t.position).padStart(2, '0') }} · {{ t.title }} ({{ ms(t.length_ms) }})
                </SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
      </div>

      <Alert v-if="missing.length || duplicates.size" variant="default" class="border-warning/30">
        <AlertTitle class="text-[13px]">
          {{ duplicates.size ? 'Une piste est associée à plusieurs fichiers' : `${missing.length} piste(s) sans fichier` }}
        </AlertTitle>
        <AlertDescription v-if="missing.length" class="text-[12px]">
          {{ missing.map(t => t.title).join(', ') }}
        </AlertDescription>
      </Alert>

      <div class="flex justify-end">
        <Button :disabled="apply.isPending.value || duplicates.size > 0 || !releaseId" @click="apply.mutate()">
          <Spinner v-if="apply.isPending.value" data-icon="inline-start" />
          Importer avec ce plan
        </Button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import type { Release } from '@/lib/types'
import { ArrowLeftIcon, ExternalLinkIcon, RadarIcon, XIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { toast } from 'vue-sonner'
import CandidateCard from '@/components/CandidateCard.vue'
import CoverArt from '@/components/CoverArt.vue'
import EventFeed from '@/components/EventFeed.vue'
import FormatTag from '@/components/FormatTag.vue'
import ImportReview from '@/components/ImportReview.vue'
import TrackCoverage from '@/components/TrackCoverage.vue'
import SignalChain from '@/components/SignalChain.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TransferRow from '@/components/TransferRow.vue'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAlbum } from '@/composables/queries'
import { api } from '@/lib/api'
import { ago, bytes, ms, year } from '@/lib/format'
import { ALBUM_STATUS, RELEASE_TYPES, SECONDARY_TYPES } from '@/lib/status'
import { cn } from '@/lib/utils'

const route = useRoute()
const qc = useQueryClient()
const id = computed(() => Number(route.params.id))
const { data: album, isPending } = useAlbum(id)

const tab = ref('candidates')
const viewRelease = ref<string>('')
const showRejected = ref(false)

watch(album, (a) => {
  if (!a)
    return
  if (!viewRelease.value)
    viewRelease.value = String(a.selected_release_id ?? a.releases[0]?.id ?? '')
}, { immediate: true })

const release = computed<Release | undefined>(() =>
  album.value?.releases.find(r => String(r.id) === viewRelease.value),
)
const proposed = computed(() => (album.value?.candidates ?? []).filter(c => c.status !== 'rejected'))
const rejected = computed(() => (album.value?.candidates ?? []).filter(c => c.status === 'rejected'))
const reviewCandidate = computed(() =>
  album.value?.status === 'needs_review'
    ? album.value.candidates.find(c => c.status === 'downloaded')
    : undefined,
)
const present = computed(() => new Set((album.value?.files ?? []).map(f => f.recording_mbid).filter(Boolean)))
/** Fichiers audio reçus / demandés, par candidat */
const received = computed(() => {
  const out: Record<number, { done: number, total: number }> = {}
  for (const t of album.value?.transfers ?? []) {
    if (!t.candidate_id || !/\.(flac|mp3|m4a|aac|ogg|opus|wav|aiff?|alac|ape|wv|wma)$/i.test(t.remote_path))
      continue
    const r = (out[t.candidate_id] ??= { done: 0, total: 0 })
    r.total++
    if (t.state === 'complete')
      r.done++
  }
  return out
})
const canApprove = computed(() => !!album.value && !['downloading', 'importing', 'searching'].includes(album.value.status))
const typeLabel = computed(() => {
  const a = album.value
  if (!a)
    return ''
  const parts = [RELEASE_TYPES[a.primary_type ?? 'other'] ?? a.primary_type, ...a.secondary_types.map(s => SECONDARY_TYPES[s] ?? s)]
  return parts.filter(Boolean).join(' · ')
})

function refresh() {
  qc.invalidateQueries({ queryKey: ['album'] })
}

const hunt = useMutation({
  mutationFn: () => api.post(`/albums/${id.value}/hunt`),
  onSuccess: () => toast.info('Recherche lancée', { description: 'Les requêtes et les décisions apparaissent dans l’historique.' }),
})
const approving = ref<number | null>(null)
const approve = useMutation({
  mutationFn: (cid: number) => {
    approving.value = cid
    return api.post(`/candidates/${cid}/approve`)
  },
  onSuccess: (d) => {
    const r = d as { resumed?: boolean, missing?: number }
    toast.success(r.resumed ? `Reprise : ${r.missing} fichier(s) redemandé(s)` : 'Téléchargement lancé', {
      description: 'Suis la progression dans l’onglet Transferts.',
    })
    refresh()
  },
  onError: e => toast.error(e.message),
  onSettled: () => (approving.value = null),
})
const monitor = useMutation({
  mutationFn: (monitored: boolean) => api.patch(`/albums/${id.value}`, { monitored }),
  onSuccess: refresh,
})
const selectRelease = useMutation({
  mutationFn: (rid: number) => api.patch(`/albums/${id.value}`, { selected_release_id: rid }),
  onSuccess: () => {
    toast.success('Édition retenue pour la recherche et l’import')
    refresh()
  },
})
const dismiss = useMutation({
  mutationFn: () => api.post(`/albums/${id.value}/dismiss`),
  onSuccess: refresh,
})
</script>

<template>
  <div class="flex flex-col gap-8">
    <RouterLink
      v-if="album?.artist"
      :to="{ name: 'artist', params: { id: album.artist.id } }"
      class="inline-flex w-fit items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground"
    >
      <ArrowLeftIcon class="size-3.5" />
      {{ album.artist.name }}
    </RouterLink>

    <div v-if="isPending" class="flex gap-8">
      <Skeleton class="size-52" />
      <div class="flex flex-1 flex-col gap-3">
        <Skeleton class="h-12 w-1/2" />
        <Skeleton class="h-4 w-1/3" />
      </div>
    </div>

    <template v-else-if="album">
      <header class="grid gap-7 md:grid-cols-[208px_minmax(0,1fr)]">
        <CoverArt :mbid="album.mbid" :size="500" class="w-full max-w-[208px]" :alt="album.title" />
        <div class="flex min-w-0 flex-col justify-end gap-4">
          <div class="flex flex-col gap-2">
            <p class="legend">
              {{ typeLabel }} · {{ year(album.first_release_date) }}
            </p>
            <h1 class="spine text-[46px] text-balance md:text-[64px]">
              {{ album.title }}
            </h1>
            <p class="text-[14px] text-muted-foreground">
              {{ album.artist?.name }}
              <span class="text-faint">· {{ album.artist?.mode === 'auto' ? 'mode automatique' : 'mode validation' }}</span>
            </p>
          </div>

          <div class="flex flex-col gap-3 rounded-lg border bg-card p-4 lg:flex-row lg:items-center lg:justify-between">
            <div class="flex flex-col gap-2.5">
              <SignalChain :status="album.status" size="lg" labels />
              <p class="flex flex-wrap items-center gap-2 text-[12.5px]">
                <StatusBadge :status="album.status" />
                <span class="text-muted-foreground">{{ album.status_reason ?? ALBUM_STATUS[album.status].hint }}</span>
              </p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <label class="mr-2 flex items-center gap-2 text-[12.5px] text-muted-foreground">
                <Switch :model-value="album.monitored" @update:model-value="(v: boolean) => monitor.mutate(v)" />
                Suivi
              </label>
              <Button
                v-if="album.status === 'pending_approval'"
                variant="ghost"
                size="sm"
                class="text-muted-foreground"
                @click="dismiss.mutate()"
              >
                <XIcon data-icon="inline-start" />
                Tout refuser
              </Button>
              <Button
                size="sm"
                variant="outline"
                :disabled="hunt.isPending.value || album.status === 'searching' || album.status === 'downloading'"
                @click="hunt.mutate()"
              >
                <RadarIcon data-icon="inline-start" />
                {{ album.status === 'imported' ? 'Chercher mieux' : 'Chercher maintenant' }}
              </Button>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-faint">
            <span v-if="album.imported_format" class="flex items-center gap-1.5">Présent en <FormatTag :format="album.imported_format" /></span>
            <span v-if="album.imported_path" class="min-w-0 truncate font-mono" :title="album.imported_path">{{ album.imported_path }}</span>
            <span>Dernière recherche {{ ago(album.last_searched_at) }}</span>
            <a :href="`https://musicbrainz.org/release-group/${album.mbid}`" target="_blank" rel="noreferrer" class="inline-flex items-center gap-1 hover:text-primary">
              MusicBrainz <ExternalLinkIcon class="size-3" />
            </a>
          </div>
        </div>
      </header>

      <ImportReview v-if="reviewCandidate" :candidate-id="reviewCandidate.id" :releases="album.releases" />

      <TrackCoverage :album-id="album.id" />

      <Tabs v-model="tab" class="gap-5">
        <TabsList>
          <TabsTrigger value="candidates">
            Candidats <span class="ml-1 font-mono text-[11px] text-faint tnum">{{ album.candidates.length }}</span>
          </TabsTrigger>
          <TabsTrigger value="tracks">
            Tracklist
          </TabsTrigger>
          <TabsTrigger value="files">
            Fichiers <span class="ml-1 font-mono text-[11px] text-faint tnum">{{ album.files.length }}</span>
          </TabsTrigger>
          <TabsTrigger value="transfers">
            Transferts
          </TabsTrigger>
          <TabsTrigger value="history">
            Historique
          </TabsTrigger>
        </TabsList>

        <TabsContent value="candidates" class="flex flex-col gap-4">
          <div v-if="album.search_runs.length" class="flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-muted-foreground">
            <span v-for="r in album.search_runs.slice(0, 4)" :key="r.id">
              <span class="font-mono text-foreground/80">« {{ r.query }} »</span>
              <span class="text-faint"> → {{ r.result_count }} fichiers, {{ r.peer_count }} pairs, {{ ago(r.started_at) }}</span>
            </span>
          </div>
          <Empty v-if="!album.candidates.length" class="rounded-lg border border-dashed py-12">
            <EmptyHeader>
              <EmptyTitle class="text-[14px]">
                Aucun candidat pour l’instant
              </EmptyTitle>
              <EmptyDescription class="text-[12.5px]">
                Lance une recherche : chaque dossier trouvé sera noté (tracklist, format, disponibilité du pair) et tu verras pourquoi il est retenu ou écarté.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
          <CandidateCard
            v-for="(c, i) in proposed"
            :key="c.id"
            :candidate="c"
            :rank="i + 1"
            :received="received[c.id]"
            :can-approve="canApprove && ['proposed', 'failed'].includes(c.status)"
            :busy="approving === c.id"
            @approve="approve.mutate"
          />
          <template v-if="rejected.length">
            <button
              type="button"
              class="w-fit text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              @click="showRejected = !showRejected"
            >
              {{ showRejected ? 'Masquer' : 'Voir' }} les {{ rejected.length }} dossiers écartés et pourquoi
            </button>
            <template v-if="showRejected">
              <CandidateCard
                v-for="c in rejected"
                :key="c.id"
                :candidate="c"
                :can-approve="canApprove"
                :busy="approving === c.id"
                @approve="approve.mutate"
              />
            </template>
          </template>
        </TabsContent>

        <TabsContent value="tracks" class="flex flex-col gap-4">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
            <Select v-model="viewRelease">
              <SelectTrigger class="w-full sm:max-w-xl">
                <SelectValue placeholder="Édition" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem v-for="r in album.releases" :key="r.id" :value="String(r.id)">
                    {{ r.title }}{{ r.disambiguation ? ` (${r.disambiguation})` : '' }} · {{ r.date ?? '?' }} · {{ r.country ?? '?' }} · {{ r.formats || '?' }} · {{ r.track_count }} pistes
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <Button
              v-if="release && String(album.selected_release_id) !== viewRelease"
              variant="outline"
              size="sm"
              @click="selectRelease.mutate(release.id)"
            >
              Retenir cette édition
            </Button>
            <span v-else-if="release" class="text-[12px] text-success">Édition retenue</span>
          </div>
          <p v-if="release" class="text-[12px] text-faint">
            {{ release.label ?? 'Label inconnu' }}<template v-if="release.barcode">
              · code-barres <span class="font-mono">{{ release.barcode }}</span>
            </template> · {{ album.releases.length }} édition(s) connue(s) sur MusicBrainz
          </p>
          <div v-if="release" class="overflow-hidden rounded-lg border bg-card">
            <div
              v-for="t in release.tracks"
              :key="t.id"
              class="grid grid-cols-[3rem_minmax(0,1fr)_auto_1rem] items-center gap-3 border-b px-4 py-2 text-[13px] last:border-b-0"
            >
              <span class="font-mono text-[11.5px] text-faint tnum">{{ release.disc_count > 1 ? `${t.disc}-` : '' }}{{ String(t.position).padStart(2, '0') }}</span>
              <span class="truncate">{{ t.title }}<span v-if="t.artist_credit && t.artist_credit !== album.artist?.name" class="text-faint"> · {{ t.artist_credit }}</span></span>
              <span class="font-mono text-[11.5px] text-muted-foreground tnum">{{ ms(t.length_ms) }}</span>
              <span
                :class="cn('size-1.5 rounded-full', present.has(t.recording_mbid) ? 'bg-success' : 'bg-border-strong')"
                :title="present.has(t.recording_mbid) ? 'Présent dans la bibliothèque' : 'Absent'"
              />
            </div>
          </div>
          <p v-else class="text-[12.5px] text-faint">
            Tracklist indisponible (MusicBrainz injoignable ?).
          </p>
        </TabsContent>

        <TabsContent value="files">
          <div v-if="album.files.length" class="overflow-hidden rounded-lg border bg-card">
            <div
              v-for="f in album.files"
              :key="f.id"
              class="flex items-center gap-3 border-b px-4 py-2 last:border-b-0"
            >
              <FormatTag :format="f.format" />
              <span class="min-w-0 flex-1 truncate font-mono text-[12px]" :title="f.path">{{ f.path }}</span>
              <span class="font-mono text-[11.5px] text-faint tnum">{{ bytes(f.size) }}</span>
            </div>
          </div>
          <p v-else class="rounded-lg border border-dashed px-4 py-6 text-[12.5px] text-faint">
            Aucun fichier de cet album dans la bibliothèque. Les fichiers sont reconnus grâce à leurs tags MusicBrainz.
          </p>
        </TabsContent>

        <TabsContent value="transfers">
          <div v-if="album.transfers.length" class="flex flex-col divide-y rounded-lg border bg-card px-4">
            <TransferRow v-for="t in album.transfers" :key="t.id" :transfer="t" :actions="false" />
          </div>
          <p v-else class="rounded-lg border border-dashed px-4 py-6 text-[12.5px] text-faint">
            Aucun transfert pour cet album.
          </p>
        </TabsContent>

        <TabsContent value="history">
          <EventFeed v-if="album.events.length" :events="album.events" :links="false" />
          <p v-else class="text-[12.5px] text-faint">
            Pas encore d’historique.
          </p>
        </TabsContent>
      </Tabs>
    </template>
  </div>
</template>

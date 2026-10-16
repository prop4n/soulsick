<script setup lang="ts">
import { InboxIcon, PlusIcon, RadarIcon } from '@lucide/vue'
import { useMutation } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import AddArtistDialog from '@/components/AddArtistDialog.vue'
import AlbumRow from '@/components/AlbumRow.vue'
import EventFeed from '@/components/EventFeed.vue'
import PageHeader from '@/components/PageHeader.vue'
import TransferRow from '@/components/TransferRow.vue'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { useAlbums, useEvents, useStatus, useTransfers } from '@/composables/queries'
import { api } from '@/lib/api'
import { bytes, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'

const live = useLive()
const { data: status } = useStatus()
const { data: attention, isPending: attentionLoading } = useAlbums('pending_approval,needs_review')
const { data: inflight } = useAlbums('searching,downloading,importing')
const { data: downloads } = useTransfers(ref('download'))
const { data: recent } = useEvents(ref({ limit: 40 }))
const addOpen = ref(false)

const feed = computed(() => {
  const seen = new Set(live.events.map(e => e.id))
  return [...live.events, ...(recent.value ?? []).filter(e => !seen.has(e.id))].slice(0, 30)
})

const active = computed(() =>
  (downloads.value ?? []).filter(t => ['queued', 'initializing', 'transferring'].includes(live.transfers.get(t.id)?.state ?? t.state)).slice(0, 6),
)

/** La chaîne en grand : combien d'albums à chaque étape. */
const stages = computed(() => {
  const a = status.value?.albums ?? {}
  return [
    { key: 'wanted', label: 'Recherchés', hint: 'en attente de chasse', n: (a.wanted ?? 0) + (a.searching ?? 0) + (a.failed ?? 0), tone: 'text-foreground' },
    { key: 'found', label: 'Trouvés', hint: 'à valider par toi', n: a.pending_approval ?? 0, tone: (a.pending_approval ?? 0) ? 'text-warning' : 'text-foreground' },
    { key: 'received', label: 'En réception', hint: 'téléchargement et import', n: (a.downloading ?? 0) + (a.importing ?? 0), tone: (a.downloading ?? 0) ? 'text-primary' : 'text-foreground' },
    { key: 'shelved', label: 'Rangés', hint: 'dans la bibliothèque', n: a.imported ?? 0, tone: 'text-success' },
  ]
})

const runHunt = useMutation({
  mutationFn: () => api.post<{ queued: number }>('/hunter/run'),
  onSuccess: d => toast.success(d.queued ? `Chasse lancée pour ${plural(d.queued, 'album')}` : 'Rien à chercher pour le moment'),
  onError: e => toast.error(e.message),
})
</script>

<template>
  <div class="flex flex-col gap-8">
    <PageHeader eyebrow="Console" title="Ce qui se passe, ce qui t’attend">
      <template #actions>
        <Button variant="outline" size="sm" :disabled="runHunt.isPending.value" @click="runHunt.mutate()">
          <RadarIcon data-icon="inline-start" />
          Chasser maintenant
        </Button>
        <Button size="sm" @click="addOpen = true">
          <PlusIcon data-icon="inline-start" />
          Suivre un artiste
        </Button>
      </template>
    </PageHeader>

    <!-- La chaîne -->
    <section aria-label="La chaîne" class="grid grid-cols-2 overflow-hidden rounded-lg border bg-card md:grid-cols-4">
      <div
        v-for="(s, i) in stages"
        :key="s.key"
        :class="cn('relative flex flex-col gap-3 p-5', i > 0 && 'border-l', i >= 2 && 'max-md:border-t', i === 2 && 'max-md:border-l-0')"
      >
        <div class="flex items-center gap-2">
          <span class="font-mono text-[10.5px] text-faint tnum">0{{ i + 1 }}</span>
          <span class="legend !text-muted-foreground">{{ s.label }}</span>
        </div>
        <div :class="cn('spine text-[56px] tnum', s.tone)">
          <Skeleton v-if="!status" class="h-8 w-14" />
          <template v-else>
            {{ s.n }}
          </template>
        </div>
        <div class="flex items-center gap-[3px]">
          <span
            v-for="j in 4"
            :key="j"
            :class="cn('h-1 flex-1 rounded-[1px]', j - 1 <= i ? (i === 3 ? 'bg-success/70' : 'bg-primary/70') : 'bg-border-strong')"
          />
        </div>
        <p class="text-[12px] text-faint">
          {{ s.hint }}
        </p>
      </div>
    </section>

    <div class="grid gap-8 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="flex min-w-0 flex-col gap-8">
        <!-- Attention -->
        <section class="flex flex-col gap-3">
          <div class="flex items-baseline justify-between">
            <h2 class="text-[14px] font-semibold">
              Demande ton attention
            </h2>
            <RouterLink v-if="attention?.length" :to="{ name: 'queue' }" class="text-[12px] text-muted-foreground hover:text-primary">
              Toute la file →
            </RouterLink>
          </div>
          <div v-if="attentionLoading" class="flex flex-col gap-2">
            <Skeleton v-for="i in 3" :key="i" class="h-14 w-full" />
          </div>
          <div v-else-if="attention?.length" class="flex flex-col rounded-lg border bg-card p-1.5">
            <AlbumRow v-for="a in attention.slice(0, 6)" :key="a.id" :album="a" show-artist />
          </div>
          <Empty v-else class="rounded-lg border border-dashed py-8">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <InboxIcon />
              </EmptyMedia>
              <EmptyTitle class="text-[14px]">
                Rien à valider
              </EmptyTitle>
              <EmptyDescription class="text-[12.5px]">
                Les albums des artistes en mode validation apparaîtront ici avec leurs candidats notés.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        </section>

        <!-- En cours -->
        <section v-if="inflight?.length" class="flex flex-col gap-3">
          <h2 class="text-[14px] font-semibold">
            En cours
          </h2>
          <div class="flex flex-col rounded-lg border bg-card p-1.5">
            <AlbumRow v-for="a in inflight.slice(0, 6)" :key="a.id" :album="a" show-artist />
          </div>
        </section>

        <section class="flex flex-col gap-3">
          <div class="flex items-baseline justify-between">
            <h2 class="text-[14px] font-semibold">
              Réception en direct
            </h2>
            <RouterLink :to="{ name: 'transfers' }" class="text-[12px] text-muted-foreground hover:text-primary">
              Tous les transferts →
            </RouterLink>
          </div>
          <div v-if="active.length" class="flex flex-col divide-y rounded-lg border bg-card px-4">
            <TransferRow v-for="t in active" :key="t.id" :transfer="t" :actions="false" />
          </div>
          <p v-else class="rounded-lg border border-dashed px-4 py-5 text-[12.5px] text-faint">
            Aucun téléchargement actif.
          </p>
        </section>
      </div>

      <aside class="flex flex-col gap-8">
        <section class="flex flex-col gap-3">
          <h2 class="text-[14px] font-semibold">
            Bibliothèque
          </h2>
          <dl class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border">
            <div class="flex flex-col gap-1 bg-card p-4">
              <dt class="legend">
                Artistes suivis
              </dt>
              <dd class="font-mono text-[20px] tnum">
                {{ status?.artists ?? '—' }}
              </dd>
            </div>
            <div class="flex flex-col gap-1 bg-card p-4">
              <dt class="legend">
                Fichiers
              </dt>
              <dd class="font-mono text-[20px] tnum">
                {{ status?.library.files ?? '—' }}
              </dd>
            </div>
            <div class="col-span-2 flex flex-col gap-2.5 bg-card p-4 text-[12px]">
              <div class="flex items-center justify-between gap-3">
                <span class="text-faint">Taille</span>
                <span class="font-mono text-muted-foreground tnum">{{ bytes(status?.library.size) }}</span>
              </div>
              <div class="flex items-center justify-between gap-3">
                <span class="shrink-0 text-faint">Rangement</span>
                <span class="truncate font-mono text-muted-foreground" :title="status?.paths.music">{{ status?.paths.music }}</span>
              </div>
              <div class="flex items-center justify-between gap-3">
                <span class="shrink-0 text-faint">Réception</span>
                <span class="truncate font-mono text-muted-foreground" :title="status?.paths.downloads">{{ status?.paths.downloads }}</span>
              </div>
              <div class="flex items-center justify-between gap-3">
                <span class="shrink-0 text-faint">Partagés</span>
                <span class="font-mono text-muted-foreground tnum">{{ live.engine ? `${live.engine.shared_files} fichiers · ${live.engine.shared_folders} dossiers` : '—' }}</span>
              </div>
            </div>
          </dl>
        </section>

        <section class="flex min-h-0 flex-col gap-1">
          <div class="flex items-baseline justify-between">
            <h2 class="text-[14px] font-semibold">
              Dernières décisions
            </h2>
            <RouterLink :to="{ name: 'journal' }" class="text-[12px] text-muted-foreground hover:text-primary">
              Journal →
            </RouterLink>
          </div>
          <EventFeed :events="feed" compact />
        </section>
      </aside>
    </div>

    <AddArtistDialog v-model:open="addOpen" />
  </div>
</template>

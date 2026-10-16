<script setup lang="ts">
import type { ArtistDetail, ArtistMode, ReleaseGroup } from '@/lib/types'
import { ArrowLeftIcon, ChevronDownIcon, ExternalLinkIcon, RadarIcon, RefreshCwIcon, Trash2Icon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import CoverArt from '@/components/CoverArt.vue'
import EventFeed from '@/components/EventFeed.vue'
import FormatTag from '@/components/FormatTag.vue'
import SignalChain from '@/components/SignalChain.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Field, FieldLabel } from '@/components/ui/field'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useArtist, useEvents, useProfiles } from '@/composables/queries'
import { api } from '@/lib/api'
import { ago, year } from '@/lib/format'
import { RELEASE_TYPES, SECONDARY_TYPES } from '@/lib/status'
import { cn } from '@/lib/utils'

const route = useRoute()
const router = useRouter()
const qc = useQueryClient()
const id = computed(() => Number(route.params.id))
const { data: artist, isPending } = useArtist(id)
const { data: profiles } = useProfiles()
const { data: events } = useEvents(computed(() => ({ artist_id: id.value, limit: 60 })))
const showIgnored = ref(true)

const sections = computed(() => {
  const groups = new Map<string, ReleaseGroup[]>()
  for (const rg of artist.value?.release_groups ?? []) {
    if (!showIgnored.value && !rg.monitored && rg.status === 'ignored')
      continue
    const key = rg.secondary_types[0] ?? rg.primary_type ?? 'other'
    if (!groups.has(key))
      groups.set(key, [])
    groups.get(key)!.push(rg)
  }
  const order = ['album', 'ep', 'single', 'live', 'compilation', 'soundtrack', 'remix', 'broadcast', 'other']
  return [...groups.entries()]
    .sort((a, b) => (order.indexOf(a[0]) + 1 || 99) - (order.indexOf(b[0]) + 1 || 99))
    .map(([key, items]) => ({ key, label: RELEASE_TYPES[key] ?? SECONDARY_TYPES[key] ?? key, items }))
})
const hiddenCount = computed(() => (artist.value?.release_groups ?? []).filter(r => !r.monitored && r.status === 'ignored').length)

function refresh() {
  qc.invalidateQueries({ queryKey: ['artist'] })
  qc.invalidateQueries({ queryKey: ['artists'] })
}

const patch = useMutation({
  mutationFn: (body: Record<string, unknown>) => api.patch(`/artists/${id.value}`, body),
  onSuccess: refresh,
  onError: e => toast.error(e.message),
})
const albumMonitor = useMutation({
  mutationFn: ({ rid, monitored }: { rid: number, monitored: boolean }) => api.patch(`/albums/${rid}`, { monitored }),
  // L'interrupteur bascule tout de suite ; le serveur confirme ensuite
  onMutate: ({ rid, monitored }) => {
    qc.setQueryData<ArtistDetail>(['artist', id], old => old && {
      ...old,
      release_groups: old.release_groups.map(rg => (rg.id === rid ? { ...rg, monitored } : rg)),
    })
  },
  onError: e => toast.error(e.message),
  onSettled: refresh,
})
const bulk = useMutation({
  mutationFn: (body: { scope: 'all' | 'none' | 'future', section?: string }) =>
    api.post<{ changed: number }>(`/artists/${id.value}/monitor`, body),
  onSuccess: (d, v) => {
    const what = { all: 'suivie(s)', none: 'plus suivie(s)', future: 'suivie(s) seulement si à venir' }[v.scope]
    toast.success(d.changed ? `${d.changed} sortie(s) ${what}` : 'Rien à changer')
    refresh()
  },
  onError: e => toast.error(e.message),
})
const sync = useMutation({
  mutationFn: () => api.post(`/artists/${id.value}/sync`),
  onSuccess: () => toast.info('Synchronisation MusicBrainz lancée'),
})
const hunt = useMutation({
  mutationFn: () => api.post<{ queued: number }>(`/artists/${id.value}/hunt`),
  onSuccess: d => toast.info(d.queued ? `${d.queued} album(s) en chasse` : 'Aucun album recherché pour cet artiste'),
})
const huntOne = useMutation({
  mutationFn: (rid: number) => api.post(`/albums/${rid}/hunt`),
  onSuccess: () => toast.info('Recherche lancée — suis-la dans l’activité'),
})
const remove = useMutation({
  mutationFn: () => api.del(`/artists/${id.value}`),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['artists'] })
    router.push({ name: 'artists' })
  },
})

const leadCover = computed(() => artist.value?.stats.cover_mbid)
</script>

<template>
  <div class="flex flex-col gap-8">
    <RouterLink :to="{ name: 'artists' }" class="inline-flex w-fit items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground">
      <ArrowLeftIcon class="size-3.5" />
      Artistes
    </RouterLink>

    <div v-if="isPending" class="flex gap-6">
      <Skeleton class="size-36" />
      <div class="flex flex-1 flex-col gap-3">
        <Skeleton class="h-10 w-1/3" />
        <Skeleton class="h-4 w-1/4" />
      </div>
    </div>

    <template v-else-if="artist">
      <header class="flex flex-col gap-6 md:flex-row md:items-end">
        <CoverArt :mbid="leadCover" :size="500" class="size-32 shrink-0 md:size-40" :alt="artist.name" />
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <p class="legend">
            Artiste{{ artist.type ? ` · ${artist.type}` : '' }}{{ artist.country ? ` · ${artist.country}` : '' }}
          </p>
          <h1 class="spine text-[48px] text-foreground text-balance md:text-[68px]">
            {{ artist.name }}
          </h1>
          <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted-foreground">
            <span v-if="artist.disambiguation">{{ artist.disambiguation }}</span>
            <span class="font-mono text-faint tnum">{{ artist.stats.imported }}/{{ artist.stats.monitored }} albums suivis rangés</span>
            <span class="text-faint">synchronisé {{ ago(artist.last_synced_at) }}</span>
            <a
              :href="`https://musicbrainz.org/artist/${artist.mbid}`"
              target="_blank"
              rel="noreferrer"
              class="inline-flex items-center gap-1 text-faint hover:text-primary"
            >MusicBrainz <ExternalLinkIcon class="size-3" /></a>
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button variant="outline" size="sm" :disabled="bulk.isPending.value">
                Suivi des sorties
                <ChevronDownIcon data-icon="inline-end" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-64">
              <DropdownMenuLabel class="text-[11.5px] font-normal text-muted-foreground">
                S’applique à toute la discographie connue. Ce qui est déjà rangé ou en cours n’est pas touché.
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem @select="bulk.mutate({ scope: 'none' })">
                  Ne rien suivre
                </DropdownMenuItem>
                <DropdownMenuItem @select="bulk.mutate({ scope: 'future' })">
                  Seulement les sorties à venir
                </DropdownMenuItem>
                <DropdownMenuItem @select="bulk.mutate({ scope: 'all' })">
                  Tout suivre
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button variant="outline" size="sm" :disabled="sync.isPending.value" @click="sync.mutate()">
            <RefreshCwIcon data-icon="inline-start" />
            Synchroniser
          </Button>
          <Button size="sm" :disabled="hunt.isPending.value" @click="hunt.mutate()">
            <RadarIcon data-icon="inline-start" />
            Chasser les manquants
          </Button>
        </div>
      </header>

      <!-- Réglages de suivi, en ligne : pas de page cachée -->
      <section class="grid gap-5 rounded-lg border bg-card p-5 md:grid-cols-[auto_auto_minmax(0,1fr)_auto] md:items-end">
        <Field orientation="horizontal" class="w-auto">
          <Switch
            id="mon"
            :model-value="artist.monitored"
            @update:model-value="(v: boolean) => patch.mutate({ monitored: v })"
          />
          <FieldLabel for="mon" class="text-[13px]">
            Suivi actif
          </FieldLabel>
        </Field>
        <Field class="w-auto">
          <FieldLabel class="legend">
            Décision
          </FieldLabel>
          <ToggleGroup
            :model-value="artist.mode"
            type="single"
            variant="outline"
            size="sm"
            @update:model-value="(v) => v && patch.mutate({ mode: v as ArtistMode })"
          >
            <ToggleGroupItem value="validation">
              Me demander
            </ToggleGroupItem>
            <ToggleGroupItem value="auto">
              Automatique
            </ToggleGroupItem>
          </ToggleGroup>
        </Field>
        <Field class="min-w-0">
          <FieldLabel class="legend">
            Sorties suivies
          </FieldLabel>
          <ToggleGroup
            :model-value="artist.primary_types"
            type="multiple"
            variant="outline"
            size="sm"
            class="flex-wrap justify-start"
            @update:model-value="(v) => patch.mutate({ primary_types: v })"
          >
            <ToggleGroupItem v-for="(label, key) in RELEASE_TYPES" :key="key" :value="key">
              {{ label }}
            </ToggleGroupItem>
          </ToggleGroup>
        </Field>
        <Field class="w-full md:w-52">
          <FieldLabel class="legend">
            Profil qualité
          </FieldLabel>
          <Select
            :model-value="artist.quality_profile_id ? String(artist.quality_profile_id) : undefined"
            @update:model-value="(v) => patch.mutate({ quality_profile_id: Number(v) })"
          >
            <SelectTrigger size="sm" class="w-full">
              <SelectValue placeholder="Par défaut" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem v-for="p in profiles ?? []" :key="p.id" :value="String(p.id)">
                  {{ p.name }}
                </SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
      </section>

      <div class="grid gap-10 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div class="flex min-w-0 flex-col gap-8">
          <section v-for="s in sections" :key="s.key" class="flex flex-col">
            <div class="flex items-center gap-3 border-b pb-2">
              <h2 class="text-[14px] font-semibold">
                {{ s.label }}
              </h2>
              <span class="font-mono text-[11px] text-faint tnum">{{ s.items.filter(x => x.monitored).length }}/{{ s.items.length }} suivis</span>
              <div class="ml-auto flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="xs"
                  class="text-muted-foreground"
                  :disabled="bulk.isPending.value || s.items.every(x => x.monitored)"
                  @click="bulk.mutate({ scope: 'all', section: s.key })"
                >
                  Tout
                </Button>
                <Button
                  variant="ghost"
                  size="xs"
                  class="text-muted-foreground"
                  :disabled="bulk.isPending.value || !s.items.some(x => x.monitored)"
                  @click="bulk.mutate({ scope: 'none', section: s.key })"
                >
                  Rien
                </Button>
              </div>
            </div>
            <ul class="flex flex-col divide-y divide-border/70">
              <li
                v-for="rg in s.items"
                :key="rg.id"
                :class="cn('group flex items-center gap-3.5 py-2.5', !rg.monitored && rg.status === 'ignored' && 'opacity-55')"
              >
                <CoverArt :mbid="rg.mbid" class="size-10 shrink-0" :alt="rg.title" />
                <span class="w-10 shrink-0 font-mono text-[11.5px] text-faint tnum">{{ year(rg.first_release_date) }}</span>
                <RouterLink
                  :to="{ name: 'album', params: { id: rg.id } }"
                  class="flex min-w-0 flex-1 flex-col gap-0.5"
                >
                  <span class="truncate text-[13.5px] font-medium hover:text-primary">{{ rg.title }}</span>
                  <span v-if="rg.status_reason" class="truncate text-[11.5px] text-faint">{{ rg.status_reason }}</span>
                </RouterLink>
                <FormatTag v-if="rg.imported_format" :format="rg.imported_format" class="hidden sm:inline-flex" />
                <div class="hidden w-[150px] shrink-0 flex-col items-end gap-1.5 md:flex">
                  <StatusBadge :status="rg.status" />
                  <SignalChain :status="rg.status" />
                </div>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      class="text-faint opacity-0 group-hover:opacity-100 hover:text-primary focus-visible:opacity-100"
                      aria-label="Chercher maintenant"
                      :disabled="rg.status === 'searching' || rg.status === 'downloading'"
                      @click="huntOne.mutate(rg.id)"
                    >
                      <RadarIcon />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Chercher maintenant</TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <span class="inline-flex">
                      <Switch
                        :model-value="rg.monitored"
                        :aria-label="`Suivre ${rg.title}`"
                        @update:model-value="(v: boolean) => albumMonitor.mutate({ rid: rg.id, monitored: v })"
                      />
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>{{ rg.monitored ? 'Suivi : Soulsick le cherchera' : 'Non suivi' }}</TooltipContent>
                </Tooltip>
              </li>
            </ul>
          </section>
          <button
            v-if="hiddenCount"
            type="button"
            class="w-fit text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            @click="showIgnored = !showIgnored"
          >
            {{ showIgnored ? 'Masquer' : 'Afficher' }} les {{ hiddenCount }} sorties non suivies
          </button>
        </div>

        <aside class="flex flex-col gap-6">
          <section class="flex flex-col">
            <h2 class="text-[14px] font-semibold">
              Historique de l’artiste
            </h2>
            <EventFeed v-if="events?.length" :events="events" compact :links="false" />
            <p v-else class="pt-3 text-[12.5px] text-faint">
              Rien pour l’instant.
            </p>
          </section>
          <AlertDialog>
            <AlertDialogTrigger as-child>
              <Button variant="ghost" size="sm" class="w-fit text-faint hover:text-destructive">
                <Trash2Icon data-icon="inline-start" />
                Ne plus suivre cet artiste
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Ne plus suivre {{ artist.name }} ?</AlertDialogTitle>
                <AlertDialogDescription>
                  Sa discographie et ses candidats sont retirés de Soulsick. Les fichiers déjà rangés dans ta bibliothèque ne sont pas touchés.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Annuler</AlertDialogCancel>
                <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="remove.mutate()">
                  Retirer
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </aside>
      </div>
    </template>
  </div>
</template>

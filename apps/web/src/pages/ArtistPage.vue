<script setup lang="ts">
import type { ArtistDetail, ReleaseGroup } from '@/lib/types'
import { ArrowLeftIcon, CheckIcon, ChevronDownIcon, DownloadIcon, EllipsisIcon, ExternalLinkIcon, PlusIcon, XIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import CoverArt from '@/components/CoverArt.vue'
import CoverBackdrop from '@/components/CoverBackdrop.vue'
import EventFeed from '@/components/EventFeed.vue'
import FormatTag from '@/components/FormatTag.vue'
import SignalChain from '@/components/SignalChain.vue'
import SimilarArtists from '@/components/SimilarArtists.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { useCoverAccent } from '@/composables/coverAccent'
import { useArtist, useEvents } from '@/composables/queries'
import { api } from '@/lib/api'
import { ago, year } from '@/lib/format'
import { serverText } from '@/lib/serverText'
import { albumStatus, RELEASE_TYPES, releaseTypeLabel, SECONDARY_TYPES } from '@/lib/status'
import { cn } from '@/lib/utils'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const qc = useQueryClient()
const id = computed(() => Number(route.params.id))
const { data: artist, isPending } = useArtist(id)
const { data: events } = useEvents(computed(() => ({ artist_id: id.value, limit: 60 })))

/** Album, EP and single are shown; live, compilations and the rest open on demand */
const MAIN = ['album', 'ep', 'single']
const ORDER = ['album', 'ep', 'single', 'live', 'compilation', 'soundtrack', 'remix', 'broadcast', 'other']
const IN_PROGRESS = ['searching', 'downloading', 'importing', 'pending_approval', 'needs_review']
const opened = ref(new Set<string>())

/** Not in the library and not asked for: the one thing to do is get it */
const gettable = (rg: ReleaseGroup) => rg.status === 'ignored'
/** Asked for and waiting for the hunt (or its last try failed): can be given up */
const wanted = (rg: ReleaseGroup) => rg.monitored && ['wanted', 'failed'].includes(rg.status)

const sections = computed(() => {
  const groups = new Map<string, ReleaseGroup[]>()
  for (const rg of artist.value?.release_groups ?? []) {
    const key = rg.secondary_types[0] ?? rg.primary_type ?? 'other'
    if (!groups.has(key))
      groups.set(key, [])
    groups.get(key)!.push(rg)
  }
  return [...groups.entries()]
    .sort((a, b) => (ORDER.indexOf(a[0]) + 1 || 99) - (ORDER.indexOf(b[0]) + 1 || 99))
    .map(([key, items]) => ({
      key,
      label: releaseTypeLabel(key),
      items,
      inLibrary: items.filter(x => x.status === 'imported').length,
      missing: items.filter(gettable).length,
      folded: !MAIN.includes(key) && !opened.value.has(key),
    }))
})
const inLibrary = computed(() => (artist.value?.release_groups ?? []).filter(x => x.status === 'imported').length)

function toggleSection(key: string) {
  const next = new Set(opened.value)
  if (!next.delete(key))
    next.add(key)
  opened.value = next
}

function refresh() {
  qc.invalidateQueries({ queryKey: ['artist'] })
  qc.invalidateQueries({ queryKey: ['artists'] })
}
const onError = (e: Error) => toast.error(e.message)

const follow = useMutation({
  mutationFn: (on: boolean) => on ? api.post(`/artists/${id.value}/follow`) : api.del(`/artists/${id.value}/follow`),
  onSuccess: (_, on) => {
    const name = artist.value?.name
    toast.success(on ? t('artist.followDone', { name }) : t('artist.unfollowDone', { name }))
    refresh()
  },
  onError,
})
const types = useMutation({
  mutationFn: (body: { primary_types?: string[], secondary_types?: string[] }) => api.patch(`/artists/${id.value}`, body),
  onSuccess: refresh,
  onError,
})
function toggleType(kind: 'primary_types' | 'secondary_types', key: string, on: boolean) {
  const now = artist.value?.[kind] ?? []
  const next = on ? [...new Set([...now, key])] : now.filter(k => k !== key)
  if (kind === 'primary_types' && !next.length)
    return
  types.mutate({ [kind]: next })
}

const want = useMutation({
  mutationFn: ({ rid, on }: { rid: number, on: boolean }) => api.patch(`/albums/${rid}`, { monitored: on }),
  // The row changes at once; the server confirms afterwards
  onMutate: ({ rid, on }) => {
    qc.setQueryData<ArtistDetail>(['artist', id], old => old && {
      ...old,
      release_groups: old.release_groups.map((rg) => {
        if (rg.id !== rid)
          return rg
        const status = on && rg.status === 'ignored' ? 'wanted' : !on && wanted(rg) ? 'ignored' : rg.status
        return { ...rg, monitored: on, status }
      }),
    })
  },
  onSuccess: (_, { on }) => {
    if (on)
      toast.info(t('artist.getStarted'))
  },
  onError,
  onSettled: refresh,
})
const wantSection = useMutation({
  mutationFn: (section: string) => api.post<{ changed: number }>(`/artists/${id.value}/monitor`, { scope: 'all', section }),
  onSuccess: d => toast.info(d.changed ? t('artist.getMany', d.changed) : t('artist.nothingToChange')),
  onError,
  onSettled: refresh,
})
const sync = useMutation({
  mutationFn: () => api.post(`/artists/${id.value}/sync`),
  onSuccess: () => toast.info(t('artist.syncStarted')),
})
const hunt = useMutation({
  mutationFn: () => api.post<{ queued: number }>(`/artists/${id.value}/hunt`),
  onSuccess: d => toast.info(d.queued ? t('artist.huntQueued', d.queued) : t('artist.nothingWanted')),
})
const removeOpen = ref(false)
const remove = useMutation({
  mutationFn: () => api.del(`/artists/${id.value}`),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['artists'] })
    router.push({ name: 'artists' })
  },
})

const leadCover = computed(() => artist.value?.stats.cover_mbid)
const accent = useCoverAccent(leadCover)
</script>

<template>
  <div :class="cn('relative isolate flex flex-col gap-8', accent.active.value && 'cover-accent')" :style="accent.style.value">
    <CoverBackdrop :mbid="leadCover" :tinted="accent.active.value" />

    <RouterLink :to="{ name: 'artists' }" class="inline-flex w-fit items-center gap-2 text-[12px] text-muted-foreground hover:text-foreground">
      <ArrowLeftIcon class="size-4" />
      {{ t('nav.artists') }}
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
        <CoverArt
          :mbid="leadCover"
          :size="500"
          class="size-32 shrink-0 shadow-[0_24px_48px_-24px_rgb(0_0_0/0.6)] ring-1 ring-border md:size-40"
          :alt="artist.name"
        />
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <p class="legend">
            {{ t('artist.kind') }}{{ artist.type ? ` · ${artist.type}` : '' }}{{ artist.country ? ` · ${artist.country}` : '' }}
          </p>
          <h1 class="font-serif text-[48px] leading-[0.95] tracking-tight text-foreground md:text-[56px]">
            {{ artist.name }}
          </h1>
          <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
            <span v-if="artist.disambiguation">{{ artist.disambiguation }}</span>
            <span class="tnum">{{ t('artist.inLibrary', inLibrary) }}</span>
            <span class="text-faint">{{ t('artist.synced', { when: ago(artist.last_synced_at) }) }}</span>
            <a
              :href="`https://musicbrainz.org/artist/${artist.mbid}`"
              target="_blank"
              rel="noreferrer"
              class="inline-flex items-center gap-1 text-faint hover:text-primary"
            >MusicBrainz <ExternalLinkIcon class="size-3" /></a>
          </p>
        </div>

        <div class="flex items-center gap-2">
          <!-- Following: its upcoming releases come on their own -->
          <Button v-if="!artist.monitored" size="sm" :disabled="follow.isPending.value" @click="follow.mutate(true)">
            <Spinner v-if="follow.isPending.value" data-icon="inline-start" />
            <PlusIcon v-else data-icon="inline-start" />
            {{ t('artist.follow') }}
          </Button>
          <DropdownMenu v-else>
            <DropdownMenuTrigger as-child>
              <Button variant="outline" size="sm" :disabled="follow.isPending.value">
                <CheckIcon data-icon="inline-start" />
                {{ t('artist.following') }}
                <ChevronDownIcon data-icon="inline-end" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-64">
              <DropdownMenuLabel class="text-[12px] font-normal text-muted-foreground">
                {{ t('artist.followHint') }}
              </DropdownMenuLabel>
              <DropdownMenuGroup>
                <DropdownMenuCheckboxItem
                  v-for="key in RELEASE_TYPES"
                  :key="key"
                  :model-value="artist.primary_types.includes(key)"
                  @update:model-value="(v: boolean | 'indeterminate') => toggleType('primary_types', key, v === true)"
                  @select="(e: Event) => e.preventDefault()"
                >
                  {{ releaseTypeLabel(key) }}
                </DropdownMenuCheckboxItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuLabel class="text-[12px] font-normal text-muted-foreground">
                {{ t('artist.followAlso') }}
              </DropdownMenuLabel>
              <DropdownMenuGroup>
                <DropdownMenuCheckboxItem
                  v-for="key in SECONDARY_TYPES"
                  :key="key"
                  :model-value="artist.secondary_types.includes(key)"
                  @update:model-value="(v: boolean | 'indeterminate') => toggleType('secondary_types', key, v === true)"
                  @select="(e: Event) => e.preventDefault()"
                >
                  {{ releaseTypeLabel(key) }}
                </DropdownMenuCheckboxItem>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem @select="follow.mutate(false)">
                {{ t('artist.unfollow') }}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button variant="ghost" size="icon-sm" :aria-label="t('artist.more')">
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" class="w-56">
              <DropdownMenuItem @select="sync.mutate()">
                {{ t('artist.sync') }}
              </DropdownMenuItem>
              <DropdownMenuItem @select="hunt.mutate()">
                {{ t('artist.huntMissing') }}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem class="text-destructive focus:text-destructive" @select="removeOpen = true">
                {{ t('artist.remove.button') }}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <div class="grid gap-12 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div class="flex min-w-0 flex-col gap-8">
          <section v-for="s in sections" :key="s.key" class="flex flex-col">
            <div class="flex min-h-9 items-center gap-3 border-b pb-2">
              <button
                v-if="!MAIN.includes(s.key)"
                type="button"
                class="flex items-center gap-2 text-[14px] font-medium hover:text-primary"
                :aria-expanded="!s.folded"
                @click="toggleSection(s.key)"
              >
                <ChevronDownIcon :class="cn('size-4 text-muted-foreground transition-transform', s.folded && '-rotate-90')" />
                {{ s.label }}
              </button>
              <h2 v-else class="text-[14px] font-medium">
                {{ s.label }}
              </h2>
              <span class="text-[12px] text-faint tnum">{{ t('artist.sectionCount', { n: s.inLibrary, total: s.items.length }) }}</span>
              <Button
                v-if="s.missing && !s.folded"
                variant="ghost"
                size="xs"
                class="ml-auto text-muted-foreground"
                :disabled="wantSection.isPending.value"
                @click="wantSection.mutate(s.key)"
              >
                <DownloadIcon data-icon="inline-start" />
                {{ t('artist.getMissing', s.missing) }}
              </Button>
            </div>
            <ul v-if="!s.folded" class="flex flex-col divide-y divide-border">
              <li v-for="rg in s.items" :key="rg.id" class="flex min-h-14 items-center gap-3 py-2">
                <CoverArt :mbid="rg.mbid" class="size-10 shrink-0" :alt="rg.title" />
                <span class="w-10 shrink-0 font-mono text-[12px] text-faint tnum">{{ year(rg.first_release_date) }}</span>
                <RouterLink :to="{ name: 'album', params: { id: rg.id } }" class="flex min-w-0 flex-1 flex-col gap-1">
                  <span class="truncate text-[14px] hover:text-primary">{{ rg.title }}</span>
                  <span v-if="rg.status_reason && rg.status !== 'imported'" class="truncate text-[12px] text-faint">{{ serverText(rg.status_reason, rg.status_reason_t) }}</span>
                </RouterLink>

                <!-- One state per row: in the library, on its way, or to get -->
                <div class="flex shrink-0 items-center justify-end gap-2">
                  <FormatTag v-if="rg.status === 'imported'" :format="rg.imported_format" />
                  <template v-else-if="IN_PROGRESS.includes(rg.status) || wanted(rg)">
                    <span class="hidden text-[12px] text-muted-foreground sm:inline">{{ albumStatus(rg.status).label }}</span>
                    <SignalChain :status="rg.status" />
                    <Button
                      v-if="wanted(rg)"
                      variant="ghost"
                      size="icon-xs"
                      class="text-faint hover:text-foreground"
                      :aria-label="t('album.stopWanting')"
                      :title="t('album.stopWanting')"
                      @click="want.mutate({ rid: rg.id, on: false })"
                    >
                      <XIcon />
                    </Button>
                  </template>
                  <Button v-else-if="gettable(rg)" variant="outline" size="xs" @click="want.mutate({ rid: rg.id, on: true })">
                    <DownloadIcon data-icon="inline-start" />
                    {{ t('album.get') }}
                  </Button>
                </div>
              </li>
            </ul>
          </section>
        </div>

        <aside class="flex flex-col gap-8">
          <SimilarArtists :artist-id="id" />
          <section class="flex flex-col">
            <h2 class="text-[14px] font-medium">
              {{ t('artist.history') }}
            </h2>
            <EventFeed v-if="events?.length" :events="events" compact :links="false" />
            <p v-else class="pt-3 text-[13px] text-faint">
              {{ t('common.nothingYet') }}
            </p>
          </section>
        </aside>
      </div>

      <AlertDialog v-model:open="removeOpen">
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{{ t('artist.remove.title', { name: artist.name }) }}</AlertDialogTitle>
            <AlertDialogDescription>
              {{ t('artist.remove.body') }}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{{ t('common.cancel') }}</AlertDialogCancel>
            <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="remove.mutate()">
              {{ t('artist.remove.confirm') }}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </template>
  </div>
</template>

<script setup lang="ts">
import type { DeckCard, DeckResponse, DiscoverProfile } from '@/lib/types'
import { ArrowLeftIcon, ArrowRightIcon, CompassIcon, DownloadIcon, EllipsisIcon, PlusIcon, RefreshCwIcon, ShuffleIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { onKeyStroke, usePreferredReducedMotion } from '@vueuse/core'
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import DiscoverCard from '@/components/DiscoverCard.vue'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Kbd } from '@/components/ui/kbd'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

const { t } = useI18n()
const qc = useQueryClient()
const reduced = usePreferredReducedMotion()

// A deck from one angle; "another angle" asks for one that isn't the current one
const avoid = ref<string | undefined>()
const round = ref(0)
const { data, isPending, isFetching } = useQuery({
  queryKey: ['discover-deck', round],
  queryFn: () => api.get<DeckResponse>(`/discover/deck${avoid.value ? `?avoid=${avoid.value}` : ''}`),
  staleTime: Number.POSITIVE_INFINITY,
  refetchOnWindowFocus: false,
})
const cards = computed(() => data.value?.cards ?? [])
const index = ref(0)
const card = computed<DeckCard | undefined>(() => cards.value[index.value])
const next = computed<DeckCard | undefined>(() => cards.value[index.value + 1])
const tally = reactive({ followed: 0, asked: 0 })
const asked = ref(new Set<string>())

function anotherAngle() {
  avoid.value = data.value?.angle?.kind
  round.value++
}
watch(data, () => {
  index.value = 0
  tally.followed = 0
  tally.asked = 0
})

const angle = computed(() => {
  const a = data.value?.angle
  if (!a)
    return null
  if (a.kind === 'crossing') {
    const [x, y] = a.artists
    return {
      title: x && y ? t('discover.angle.crossing.title', { a: x.name, b: y.name }) : t('discover.angle.crossing.titleAny'),
      hint: t('discover.angle.crossing.hint'),
    }
  }
  if (a.kind === 'wake')
    return { title: t('discover.angle.wake.title', { name: a.artist.name }), hint: t('discover.angle.wake.hint') }
  return { title: t(`discover.angle.${a.kind}.title`), hint: t(`discover.angle.${a.kind}.hint`) }
})

// Profiles: the first cards come with theirs, the next ones are asked one card ahead
const profiles = reactive(new Map<string, DiscoverProfile | null | undefined>())
watch([card, next], () => {
  for (const c of [card.value, next.value]) {
    if (!c || profiles.has(c.mbid))
      continue
    if (c.profile !== null) {
      profiles.set(c.mbid, c.profile)
      continue
    }
    profiles.set(c.mbid, undefined) // being asked
    api.get<DiscoverProfile | Record<string, never>>(`/discover/profile/${c.mbid}`)
      .then(p => profiles.set(c.mbid, 'releases' in p ? p as DiscoverProfile : null))
      .catch(() => profiles.set(c.mbid, null))
  }
  // The photo of the next card, before it shows
  if (next.value)
    new Image().src = `/api/artist-photos/${next.value.mbid}`
}, { immediate: true })
const profileOf = (c: DeckCard) => profiles.get(c.mbid)

// The card leaves to the left (passed) or to the right (followed), then the next one comes
const view = ref<InstanceType<typeof DiscoverCard> | null>(null)
const drag = reactive({ x: 0, active: false, start: 0, leaving: 0 as -1 | 0 | 1 })
const EXIT_MS = 320
function leave(dir: -1 | 1) {
  view.value?.stopPreview()
  if (reduced.value === 'reduce') {
    index.value++
    return
  }
  drag.leaving = dir
  setTimeout(() => {
    drag.leaving = 0
    drag.x = 0
    index.value++
  }, EXIT_MS)
}
const cardStyle = computed(() => {
  if (drag.leaving)
    return { transform: `translateX(${drag.leaving * 120}%) rotate(${drag.leaving * 8}deg)`, opacity: '0' }
  return { transform: `translateX(${drag.x}px) rotate(${drag.x / 40}deg)` }
})
function onDown(e: PointerEvent) {
  if (e.pointerType === 'mouse' && e.button !== 0)
    return
  if ((e.target as HTMLElement).closest('button, a'))
    return
  drag.active = true
  drag.start = e.clientX
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}
function onMove(e: PointerEvent) {
  if (drag.active)
    drag.x = e.clientX - drag.start
}
function onUp() {
  if (!drag.active)
    return
  drag.active = false
  if (drag.x > 120)
    follow()
  else if (drag.x < -120)
    pass()
  else drag.x = 0
}

const onError = (e: Error) => toast.error(e.message)
const dismiss = useMutation({
  mutationFn: ({ mbid, days }: { mbid: string, days?: number }) => api.post('/discover/dismiss', { mbid, days }),
  onError,
})
function pass() {
  if (!card.value || drag.leaving)
    return
  dismiss.mutate({ mbid: card.value.mbid, days: 30 })
  leave(-1)
}
function notInterested() {
  if (!card.value)
    return
  dismiss.mutate({ mbid: card.value.mbid })
  leave(-1)
}
const followIt = useMutation({
  mutationFn: (c: DeckCard) => c.artist_id
    ? api.post(`/artists/${c.artist_id}/follow`)
    : api.post('/artists/bulk', { mbids: [c.mbid] }),
  onSuccess: (_, c) => {
    toast.success(t('artist.followDone', { name: c.name }), { description: t('discover.followedHint') })
    qc.invalidateQueries({ queryKey: ['artists'] })
  },
  onError,
})
function follow() {
  if (!card.value || drag.leaving)
    return
  followIt.mutate(card.value)
  tally.followed++
  leave(1)
}
const want = useMutation({
  mutationFn: ({ c, release }: { c: DeckCard, release: { mbid: string, title: string } }) =>
    api.post('/discover/want', { artist_mbid: c.mbid, release_group_mbid: release.mbid }),
  onSuccess: (_, { release }) => toast.success(t('discover.askedToast', { title: release.title })),
  onError,
})
function get(release: { mbid: string, title: string }) {
  if (!card.value || asked.value.has(release.mbid))
    return
  want.mutate({ c: card.value, release })
  asked.value = new Set([...asked.value, release.mbid])
  tally.asked++
}
/** Its best-known album you don't have yet */
const topToGet = computed(() => {
  const c = card.value
  return c ? profileOf(c)?.releases.find(r => !r.state && !asked.value.has(r.mbid)) : undefined
})
function getTop() {
  if (topToGet.value)
    get(topToGet.value)
}

// On a computer: the arrows and the space bar
const typing = (e: KeyboardEvent) => e.target instanceof HTMLElement && e.target.closest('input, textarea, [contenteditable]')
onKeyStroke('ArrowLeft', e => !typing(e) && (e.preventDefault(), pass()))
onKeyStroke('ArrowRight', e => !typing(e) && (e.preventDefault(), follow()))
onKeyStroke('ArrowUp', e => !typing(e) && (e.preventDefault(), getTop()))
onKeyStroke(' ', e => !typing(e) && !(e.target as HTMLElement)?.closest('button') && (e.preventDefault(), view.value?.togglePreview()))

const refresh = useMutation({
  mutationFn: () => api.post<{ refreshed: number }>('/discover/refresh'),
  onSuccess: (r) => {
    toast.success(t('discover.refreshed', { n: r.refreshed }))
    qc.invalidateQueries({ queryKey: ['similar'] })
    anotherAngle()
  },
  onError: e => toast.error(t('discover.refreshFailed'), { description: e.message }),
})
</script>

<template>
  <div class="flex flex-col gap-8">
    <header class="flex flex-col gap-4 sm:flex-row sm:items-end">
      <div class="flex min-w-0 flex-1 flex-col gap-2">
        <p class="legend">
          {{ t('discover.title') }}
        </p>
        <Skeleton v-if="isPending" class="h-10 w-2/3" />
        <h1 v-else class="font-serif text-[36px] leading-tight tracking-tight text-balance md:text-[44px]">
          {{ angle?.title ?? t('discover.title') }}
        </h1>
        <p v-if="angle" class="text-[14px] text-muted-foreground">
          {{ angle.hint }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span v-if="card" class="mr-2 text-[13px] text-faint tnum">{{ t('discover.position', { n: index + 1, total: cards.length }) }}</span>
        <Button v-if="data?.angle" variant="outline" size="sm" :disabled="isFetching" @click="anotherAngle()">
          <ShuffleIcon data-icon="inline-start" />
          {{ t('discover.otherAngle') }}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="ghost" size="icon-sm" :aria-label="t('artist.more')">
              <EllipsisIcon />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" class="w-60">
            <DropdownMenuItem :disabled="refresh.isPending.value" @select="refresh.mutate()">
              <RefreshCwIcon />
              {{ t('discover.refresh') }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>

    <p v-if="data?.pending" class="-mt-4 text-[13px] text-faint">
      {{ t('discover.pending', { n: data.pending }) }}
    </p>

    <Skeleton v-if="isPending" class="h-[440px] w-full max-w-[960px] rounded-2xl" />

    <Empty v-else-if="!cards.length" class="rounded-xl bg-card py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <CompassIcon />
        </EmptyMedia>
        <EmptyTitle>{{ data?.followed ? t('discover.emptyTitle') : t('discover.noArtistsTitle') }}</EmptyTitle>
        <EmptyDescription>
          {{ data?.followed ? t('discover.emptyHint') : t('discover.noArtistsHint') }}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>

    <!-- The end of the deck -->
    <Empty v-else-if="!card" class="max-w-[960px] rounded-2xl border bg-card py-16">
      <EmptyHeader>
        <EmptyTitle>{{ t('discover.done') }}</EmptyTitle>
        <EmptyDescription class="tnum">
          {{ [t('discover.seenCount', cards.length), t('discover.followedCount', tally.followed), t('discover.askedCount', tally.asked)].join(' · ') }}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button size="sm" @click="anotherAngle()">
          <ShuffleIcon data-icon="inline-start" />
          {{ t('discover.otherAngle') }}
        </Button>
      </EmptyContent>
    </Empty>

    <template v-else>
      <div class="relative max-w-[960px]">
        <!-- The next one waits behind -->
        <div
          v-if="next"
          aria-hidden="true"
          class="absolute inset-0 translate-y-3 scale-[0.97] rounded-2xl border bg-card opacity-60"
        />
        <div
          :class="cn('relative touch-pan-y select-none', !drag.active && 'transition-[transform,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]')"
          :style="cardStyle"
          @pointerdown="onDown"
          @pointermove="onMove"
          @pointerup="onUp"
          @pointercancel="onUp"
        >
          <DiscoverCard
            :key="card.mbid"
            ref="view"
            :card="card"
            :profile="profileOf(card)"
            :asked="asked"
            @get="get"
          />
        </div>
      </div>

      <div class="flex max-w-[960px] flex-wrap items-center gap-2">
        <Button variant="outline" @click="pass()">
          <ArrowLeftIcon data-icon="inline-start" />
          {{ t('discover.pass') }}
        </Button>
        <Button v-if="topToGet" variant="outline" @click="getTop()">
          <DownloadIcon data-icon="inline-start" />
          {{ t('discover.getTop', { title: topToGet.title }) }}
        </Button>
        <Button @click="follow()">
          <PlusIcon data-icon="inline-start" />
          {{ t('discover.follow') }}
          <ArrowRightIcon data-icon="inline-end" />
        </Button>
        <Button variant="ghost" size="sm" class="text-muted-foreground sm:ml-auto" @click="notInterested()">
          {{ t('discover.dismiss') }}
        </Button>
      </div>

      <p class="hidden items-center gap-4 text-[12px] text-faint md:flex">
        <span class="flex items-center gap-2"><Kbd>←</Kbd>{{ t('discover.keys.pass') }}</span>
        <span class="flex items-center gap-2"><Kbd>→</Kbd>{{ t('discover.keys.follow') }}</span>
        <span class="flex items-center gap-2"><Kbd>↑</Kbd>{{ t('discover.keys.get') }}</span>
        <span class="flex items-center gap-2"><Kbd>{{ t('discover.keys.space') }}</Kbd>{{ t('discover.keys.listen') }}</span>
      </p>
    </template>
  </div>
</template>

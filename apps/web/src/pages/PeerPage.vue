<script setup lang="ts">
import type { PeerHistory, PeerProfile } from '@/lib/types'
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CrownIcon,
  FolderTreeIcon,
  HeartIcon,
  MessageSquareIcon,
  RefreshCwIcon,
  ThumbsDownIcon,
} from '@lucide/vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import CoverArt from '@/components/CoverArt.vue'
import FormatTag from '@/components/FormatTag.vue'
import TransferRow from '@/components/TransferRow.vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { ago, bytes, speed } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * One Soulseek user: who they are on the network (status, shares, description) and
 * everything that went between us (files received and sent, albums they provided).
 */
const { t, n: num } = useI18n()
const route = useRoute()
const qc = useQueryClient()
const username = computed(() => route.params.username as string)
const enc = computed(() => encodeURIComponent(username.value))

const history = useQuery({
  queryKey: ['peer', username],
  queryFn: () => api.get<PeerHistory>(`/peers/${enc.value}`),
})
const profile = useQuery({
  queryKey: ['peer-profile', username],
  queryFn: () => api.get<PeerProfile>(`/peers/${enc.value}/profile`),
  staleTime: 60_000,
  retry: false,
})

async function refresh() {
  qc.setQueryData(['peer-profile', username.value], undefined)
  qc.invalidateQueries({ queryKey: ['peer', username.value] })
  await qc.fetchQuery({
    queryKey: ['peer-profile', username],
    queryFn: () => api.get<PeerProfile>(`/peers/${enc.value}/profile?refresh=true`),
  })
}

const p = computed(() => profile.data.value)
const h = computed(() => history.data.value)

// Stable hue per user for the initial-letter avatar
const hue = computed(() => [...username.value].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7))

const STATUS_TONE: Record<string, string> = {
  online: 'bg-success',
  away: 'bg-warning',
  offline: 'bg-faint',
}
const statusLabel = computed(() => {
  if (profile.isPending.value)
    return t('peerPage.status.checking')
  return t(`peerPage.status.${p.value?.status ?? 'unknown'}`)
})

const flag = computed(() => {
  const c = p.value?.country
  if (!c || c.length !== 2)
    return null
  return String.fromCodePoint(...[...c.toUpperCase()].map(ch => 0x1F1A5 + ch.charCodeAt(0)))
})

const successRate = computed(() => {
  const d = h.value?.downloads
  if (!d || !(d.complete + d.failed))
    return null
  return Math.round((d.complete / (d.complete + d.failed)) * 100)
})

const CANDIDATE_TONE: Record<string, string> = {
  imported: 'text-success',
  downloaded: 'text-primary',
  chosen: 'text-primary',
  failed: 'text-destructive',
}
</script>

<template>
  <div class="flex flex-col gap-8">
    <!-- Identity -->
    <header class="flex flex-col gap-5 sm:flex-row sm:items-end">
      <div class="relative size-24 shrink-0">
        <img
          v-if="p?.picture"
          :src="p.picture"
          :alt="t('peerPage.picture', { peer: username })"
          class="size-full rounded-2xl object-cover ring-1 ring-border"
        >
        <div
          v-else
          class="flex size-full items-center justify-center rounded-2xl font-serif text-[44px] text-white/90 italic ring-1 ring-white/10"
          :style="{ background: `linear-gradient(135deg, hsl(${hue} 45% 38%), hsl(${(hue + 50) % 360} 50% 22%))` }"
          aria-hidden="true"
        >
          {{ username.charAt(0).toUpperCase() }}
        </div>
        <span
          v-if="p?.status"
          :class="cn('absolute -right-1 -bottom-1 size-4 rounded-full ring-4 ring-background', STATUS_TONE[p.status])"
        />
      </div>

      <div class="flex min-w-0 flex-1 flex-col gap-2">
        <p class="legend">
          {{ t('peerPage.kicker') }}
        </p>
        <h1 class="flex min-w-0 items-center gap-2.5 font-mono text-[28px] leading-tight font-semibold tracking-[-0.02em]">
          <span class="truncate">{{ username }}</span>
          <span v-if="flag" class="text-[22px]" :title="p?.country ?? ''">{{ flag }}</span>
        </h1>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px] text-muted-foreground">
          <span class="flex items-center gap-1.5">
            <span :class="cn('size-2 rounded-full', p?.status ? STATUS_TONE[p.status] : 'bg-border-strong', profile.isPending.value && 'animate-pulse')" />
            {{ statusLabel }}
          </span>
          <Badge v-if="p?.privileged" variant="outline" class="gap-1 text-warning">
            <CrownIcon class="size-3" />
            {{ t('peerPage.privileged') }}
          </Badge>
          <span v-if="p && p.status && p.status !== 'offline' && !p.reachable" class="text-faint">
            {{ t('peerPage.unreachable') }}
          </span>
        </div>
      </div>

      <div class="flex shrink-0 flex-wrap gap-2">
        <Button variant="ghost" size="sm" class="text-muted-foreground" :disabled="profile.isFetching.value" @click="refresh">
          <RefreshCwIcon data-icon="inline-start" :class="cn(profile.isFetching.value && 'animate-spin')" />
          {{ t('peerPage.refresh') }}
        </Button>
        <Button variant="outline" size="sm" as-child>
          <RouterLink :to="{ name: 'chat', query: { with: username } }">
            <MessageSquareIcon data-icon="inline-start" />
            {{ t('chat.message') }}
          </RouterLink>
        </Button>
        <Button size="sm" as-child>
          <RouterLink :to="{ name: 'browse', params: { username } }">
            <FolderTreeIcon data-icon="inline-start" />
            {{ t('peerPage.browse') }}
          </RouterLink>
        </Button>
      </div>
    </header>

    <Alert v-if="profile.error.value" class="-mt-2">
      <AlertDescription>{{ t('peerPage.profileFailed') }} {{ profile.error.value.message }}</AlertDescription>
    </Alert>

    <!-- Numbers: on the network, then with you -->
    <section class="grid gap-3 lg:grid-cols-2">
      <div class="flex flex-col gap-4 rounded-xl bg-card p-5">
        <span class="legend">{{ t('peerPage.onNetwork') }}</span>
        <div v-if="profile.isPending.value" class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Skeleton v-for="i in 4" :key="i" class="h-12" />
        </div>
        <dl v-else class="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
          <div class="flex flex-col gap-1">
            <dt class="text-[11.5px] text-faint">
              {{ t('peerPage.speed') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ p?.avg_speed != null ? speed(p.avg_speed) : '—' }}
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-[11.5px] text-faint">
              {{ t('peerPage.files') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ p?.shared_files != null ? num(p.shared_files) : '—' }}
            </dd>
            <dd v-if="p?.shared_folders != null" class="text-[11px] text-faint tnum">
              {{ t('peerPage.folders', p.shared_folders) }}
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-[11.5px] text-faint">
              {{ t('peerPage.slots') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ p?.upload_slots ?? '—' }}
            </dd>
            <dd v-if="p?.has_free_slots != null" :class="cn('text-[11px]', p.has_free_slots ? 'text-success' : 'text-faint')">
              {{ p.has_free_slots ? t('peer.freeSlot') : t('peer.noFreeSlot') }}
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-[11.5px] text-faint">
              {{ t('peerPage.queue') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ p?.queue_size ?? '—' }}
            </dd>
          </div>
        </dl>
      </div>

      <div class="flex flex-col gap-4 rounded-xl bg-card p-5">
        <span class="legend">{{ t('peerPage.withYou') }}</span>
        <div v-if="history.isPending.value" class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Skeleton v-for="i in 4" :key="i" class="h-12" />
        </div>
        <dl v-else-if="h" class="grid grid-cols-2 gap-x-4 gap-y-4 sm:grid-cols-4">
          <div class="flex flex-col gap-1">
            <dt class="flex items-center gap-1 text-[11.5px] text-faint">
              <ArrowDownIcon class="size-3" />{{ t('peerPage.received') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ h.downloads?.complete ?? 0 }}
            </dd>
            <dd class="text-[11px] text-faint tnum">
              {{ bytes(h.downloads?.bytes ?? 0) }}
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="flex items-center gap-1 text-[11.5px] text-faint">
              <ArrowUpIcon class="size-3" />{{ t('peerPage.sent') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ h.uploads?.complete ?? 0 }}
            </dd>
            <dd class="text-[11px] text-faint tnum">
              {{ bytes(h.uploads?.bytes ?? 0) }}
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-[11.5px] text-faint">
              {{ t('peerPage.reliability') }}
            </dt>
            <dd :class="cn('font-mono text-[17px] font-medium tnum', successRate != null && successRate < 60 && 'text-warning')">
              {{ successRate != null ? `${successRate} %` : '—' }}
            </dd>
            <dd v-if="h.downloads?.failed" class="text-[11px] text-faint tnum">
              {{ t('peerPage.failed', h.downloads.failed) }}
            </dd>
          </div>
          <div class="flex flex-col gap-1">
            <dt class="text-[11.5px] text-faint">
              {{ t('peerPage.measured') }}
            </dt>
            <dd class="font-mono text-[17px] font-medium tnum">
              {{ h.measured_speed ? speed(h.measured_speed) : '—' }}
            </dd>
            <dd v-if="h.downloads?.first || h.uploads?.first" class="text-[11px] text-faint">
              {{ t('peerPage.since', { when: ago([h.downloads?.first, h.uploads?.first].filter(Boolean).sort()[0]) }) }}
            </dd>
          </div>
        </dl>
      </div>
    </section>

    <!-- About -->
    <section v-if="p?.description || p?.interests?.length || p?.hated_interests?.length" class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div v-if="p.description" class="flex flex-col gap-2 rounded-xl bg-card p-5">
        <span class="legend">{{ t('peerPage.about') }}</span>
        <p class="text-[13px] leading-relaxed break-words whitespace-pre-wrap text-foreground/90">
          {{ p.description }}
        </p>
      </div>
      <div v-if="p.interests?.length || p.hated_interests?.length" class="flex flex-col gap-3 rounded-xl bg-card p-5">
        <span class="legend">{{ t('peerPage.interests') }}</span>
        <div v-if="p.interests?.length" class="flex flex-wrap gap-1.5">
          <Badge v-for="i in p.interests" :key="i" variant="secondary" class="gap-1">
            <HeartIcon class="size-3 text-primary" />{{ i }}
          </Badge>
        </div>
        <div v-if="p.hated_interests?.length" class="flex flex-wrap gap-1.5">
          <Badge v-for="i in p.hated_interests" :key="i" variant="outline" class="gap-1 text-muted-foreground">
            <ThumbsDownIcon class="size-3" />{{ i }}
          </Badge>
        </div>
      </div>
    </section>

    <!-- Albums they provided -->
    <section v-if="h?.albums.length" class="flex flex-col gap-3">
      <div class="flex items-baseline justify-between gap-3">
        <h2 class="text-[15px] font-semibold">
          {{ t('peerPage.albums', h.albums.length) }}
        </h2>
        <span v-if="h.proposals" class="text-[12px] text-faint">{{ t('peerPage.proposals', h.proposals) }}</span>
      </div>
      <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <RouterLink
          v-for="a in h.albums"
          :key="a.id"
          :to="{ name: 'album', params: { id: a.id } }"
          class="group flex items-center gap-3 rounded-xl bg-card p-2.5 pr-4 transition-colors hover:bg-accent"
        >
          <CoverArt :mbid="a.mbid" :alt="a.title" class="size-14 shrink-0" />
          <div class="flex min-w-0 flex-1 flex-col gap-1">
            <span class="truncate text-[13.5px] font-medium group-hover:text-primary">{{ a.title }}</span>
            <span class="truncate text-[12px] text-muted-foreground">{{ a.artist }}<template v-if="a.year"> · {{ a.year }}</template></span>
            <div class="flex items-center gap-2">
              <FormatTag v-if="a.format" :format="a.format" />
              <span :class="cn('text-[11px] whitespace-nowrap', CANDIDATE_TONE[a.candidate_status])">{{ t(`peerPage.candidate.${a.candidate_status}`) }}</span>
            </div>
          </div>
        </RouterLink>
      </div>
    </section>

    <!-- Latest transfers -->
    <section class="flex flex-col gap-3">
      <div class="flex items-baseline justify-between gap-3">
        <h2 class="text-[15px] font-semibold">
          {{ t('peerPage.recent') }}
        </h2>
        <span v-if="h?.messages.count" class="text-[12px] text-faint">
          {{ t('peerPage.messages', h.messages.count) }} · {{ ago(h.messages.last) }}
        </span>
      </div>
      <div v-if="history.isPending.value" class="flex flex-col gap-2">
        <Skeleton v-for="i in 4" :key="i" class="h-14" />
      </div>
      <p v-else-if="!h?.recent.length" class="rounded-xl bg-card/50 px-5 py-8 text-center text-[13px] text-muted-foreground">
        {{ t('peerPage.noTransfer', { peer: username }) }}
      </p>
      <div v-else class="flex flex-col gap-1.5">
        <TransferRow v-for="tr in h.recent" :key="tr.id" :transfer="tr" :actions="false" />
      </div>
    </section>
  </div>
</template>

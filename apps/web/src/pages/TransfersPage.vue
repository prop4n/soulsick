<script setup lang="ts">
import type { Transfer } from '@/lib/types'
import type { TransferAction } from '@/composables/transferActions'
import { ArrowDownIcon, ArrowUpIcon, BrushCleaningIcon, ChevronDownIcon, FolderIcon, HistoryIcon, PauseIcon, PlayIcon, RotateCcwIcon, XIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { toast } from 'vue-sonner'
import CoverArt from '@/components/CoverArt.vue'
import PageHeader from '@/components/PageHeader.vue'
import SwitchPeerMenu from '@/components/SwitchPeerMenu.vue'
import TransferRow from '@/components/TransferRow.vue'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTransfers } from '@/composables/queries'
import { useTransferActions } from '@/composables/transferActions'
import { api } from '@/lib/api'
import { speed } from '@/lib/format'
import { cn } from '@/lib/utils'
import { isAudioName as isAudio } from '@/lib/files'
import { useLive } from '@/stores/live'

const { t } = useI18n()
const live = useLive()
const qc = useQueryClient()
const route = useRoute()
const direction = ref<'download' | 'upload'>('download')
type Filter = 'active' | 'stuck' | 'done' | 'all'
const filter = ref<Filter>(['active', 'stuck', 'done', 'all'].includes(route.query.filter as string) ? route.query.filter as Filter : 'active')
const { data, isPending } = useTransfers(direction)

const RUNNING = ['queued', 'initializing', 'transferring']
const ACTIVE = [...RUNNING, 'paused']
const stateOf = (tr: { id: number, state: string }) => live.transfers.get(tr.id)?.state ?? tr.state
const liveOf = (tr: Transfer) => ({ ...tr, ...(live.transfers.get(tr.id) ?? {}) }) as Transfer
const isStuck = (tr: Transfer) => !!(live.transfers.get(tr.id)?.stuck ?? tr.stuck) && RUNNING.includes(stateOf(tr))
const stuckCount = computed(() => (data.value ?? []).filter(isStuck).length)

const rows = computed(() => (data.value ?? []).filter((tr) => {
  const state = stateOf(tr)
  if (filter.value === 'active')
    return ACTIVE.includes(state)
  if (filter.value === 'stuck')
    return isStuck(tr)
  if (filter.value === 'done')
    return !ACTIVE.includes(state)
  return true
}))

const collator = new Intl.Collator(undefined, { numeric: true })
const fileName = (tr: Transfer) => tr.remote_path.replace(/\\/g, '/').split('/').pop() ?? ''

/**
 * You follow an album, not 12 loose lines: transfers for the same album make one card, the
 * others (taken by hand) one card per remote folder. Inside a card, the files of the attempt
 * under way come first, in track order; earlier attempts are folded away.
 */
const groups = computed(() => {
  const map = new Map<string, Transfer[]>()
  for (const tr of rows.value) {
    const dir = tr.remote_path.replace(/\\/g, '/').split('/').slice(0, -1).join('/')
    const key = tr.album ? `album:${tr.album.id}` : `${tr.username}|${dir}`
    if (!map.has(key))
      map.set(key, [])
    map.get(key)!.push(tr)
  }
  return [...map.entries()]
    .map(([key, items]) => {
      const album = items.find(x => x.album)?.album ?? null
      // The attempt under way: sources still sending, else the latest one
      const live = new Set(items.filter(x => ACTIVE.includes(stateOf(x))).map(x => x.candidate_id))
      const latest = Math.max(...items.map(x => x.candidate_id ?? 0))
      const isCurrent = (x: Transfer) => !album || ACTIVE.includes(stateOf(x)) || live.has(x.candidate_id) || (x.candidate_id ?? 0) === latest
      // Tracks in order, then what comes with them (lyrics, covers)
      const byName = (a: Transfer, b: Transfer) =>
        Number(!isAudio(fileName(a))) - Number(!isAudio(fileName(b))) || collator.compare(fileName(a), fileName(b))
      const current = items.filter(isCurrent).sort(byName)
      const older = items.filter(x => !isCurrent(x)).sort(byName)
      const peers = [...new Set(current.map(x => x.username))]
      const dir = key.includes('|') ? key.split('|')[1] : (current[0]?.remote_path.replace(/\\/g, '/').split('/').slice(0, -1).join('/') ?? '')
      const size = current.reduce((n, x) => n + (x.size ?? 0), 0)
      const got = current.reduce((n, x) => n + (stateOf(x) === 'complete' ? (x.size ?? 0) : (live.has(x.candidate_id) ? (liveOf(x).bytes_transferred ?? 0) : 0)), 0)
      return {
        key,
        album,
        peers,
        dir,
        folder: dir.split('/').pop() || dir,
        items,
        current,
        older,
        tracks: current.filter(x => isAudio(fileName(x))).length,
        done: current.filter(x => isAudio(fileName(x)) && stateOf(x) === 'complete').length,
        pct: size ? Math.min(100, (got / size) * 100) : 0,
        speed: current.reduce((n, x) => n + (stateOf(x) === 'transferring' ? (liveOf(x).speed ?? 0) : 0), 0),
        active: current.some(x => ACTIVE.includes(stateOf(x))),
        // An album source still downloading can be switched to another peer
        candidateId: current.some(x => ACTIVE.includes(stateOf(x))) ? current.find(x => x.candidate_id)?.candidate_id ?? null : null,
        stuck: items.some(isStuck),
        latest: items.reduce((m, x) => (x.created_at && x.created_at > m ? x.created_at : m), ''),
      }
    })
    // What needs you first, then what moves, then the most recent
    .sort((a, b) => Number(b.stuck) - Number(a.stuck) || Number(b.active) - Number(a.active) || b.latest.localeCompare(a.latest))
})
type Group = (typeof groups.value)[number]

/** One word for a whole card: the state that matters most among its files */
function groupState(g: Group): { label: string, badge: 'warning' | 'signal' | 'quiet' | 'success' | 'danger' } {
  const states = g.current.map(stateOf)
  if (g.stuck)
    return { label: t('transfer.stuck'), badge: 'warning' }
  if (states.includes('transferring'))
    return { label: g.speed ? speed(g.speed) : t('transfers.group.receiving'), badge: 'signal' }
  if (states.includes('initializing'))
    return { label: t('transfers.group.connecting'), badge: 'signal' }
  if (states.includes('queued')) {
    const remote = g.current.some(x => stateOf(x) === 'queued' && x.remotely_queued)
    return { label: remote ? t('transfers.group.inTheirQueue') : t('transfer.requested'), badge: remote ? 'signal' : 'quiet' }
  }
  if (states.includes('paused'))
    return { label: t('transfers.group.paused'), badge: 'quiet' }
  if (g.album?.status === 'imported' && states.every(x => x === 'complete'))
    return { label: t('transfers.group.shelved'), badge: 'success' }
  if (states.every(x => x === 'complete'))
    return { label: t('transfers.group.received'), badge: 'success' }
  if (states.some(x => x === 'failed'))
    return { label: t('transfers.group.failed'), badge: 'danger' }
  return { label: t('transfers.group.cancelled'), badge: 'quiet' }
}

// A finished card opens on demand; one under way shows its files
const toggled = ref(new Set<string>())
const isOpen = (g: Group) => g.active !== toggled.value.has(g.key)
function toggle(key: string) {
  const next = new Set(toggled.value)
  next.has(key) ? next.delete(key) : next.add(key)
  toggled.value = next
}
const showOlder = ref(new Set<string>())
function toggleOlder(key: string) {
  const next = new Set(showOlder.value)
  next.has(key) ? next.delete(key) : next.add(key)
  showOlder.value = next
}

// --- Selection ----------------------------------------------------------------------
const selected = ref(new Set<number>())
watch([direction, filter], () => (selected.value = new Set()))
// Rows that disappear (cleared, or filtered out once finished) leave the selection
watch(rows, (r) => {
  const visible = new Set(r.map(x => x.id))
  if ([...selected.value].some(id => !visible.has(id)))
    selected.value = new Set([...selected.value].filter(id => visible.has(id)))
})
function select(ids: number[], on: boolean) {
  const next = new Set(selected.value)
  ids.forEach(id => (on ? next.add(id) : next.delete(id)))
  selected.value = next
}
function checkState(items: Transfer[]): boolean | 'indeterminate' {
  const n = items.filter(x => selected.value.has(x.id)).length
  return n === 0 ? false : n === items.length ? true : 'indeterminate'
}
const allState = computed(() => checkState(rows.value))
const selection = computed(() => rows.value.filter(x => selected.value.has(x.id)))

/** What can be done to a set of transfers, given their states */
function possible(items: Transfer[]) {
  const download = direction.value === 'download'
  return {
    pause: download ? items.filter(x => RUNNING.includes(stateOf(x))) : [],
    resume: items.filter(x => stateOf(x) === 'paused'),
    retry: download ? items.filter(x => ['failed', 'aborted'].includes(stateOf(x))) : [],
    cancel: items.filter(x => ACTIVE.includes(stateOf(x))),
  }
}
const sel = computed(() => possible(selection.value))
const all = computed(() => possible(rows.value))

// --- Actions ------------------------------------------------------------------------
const { busy, run, batch } = useTransferActions()
const working = ref(false)
async function act(items: Transfer[], kind: TransferAction) {
  working.value = true
  try {
    await batch(items.map(x => x.id), kind)
    select(items.map(x => x.id), false)
  }
  finally {
    working.value = false
  }
}

/**
 * Cancelling always asks first. The dialog closes BEFORE the confirm button's click runs,
 * so what to cancel is kept apart from the open state (closing must not erase it).
 */
const confirmOpen = ref(false)
const toCancel = ref<Transfer[]>([])
function askCancel(items: Transfer[]) {
  if (!items.length)
    return
  toCancel.value = items
  confirmOpen.value = true
}
async function doCancel() {
  const items = toCancel.value
  confirmOpen.value = false
  toCancel.value = []
  if (items.length)
    await act(items, 'cancel')
}

const clear = useMutation({
  mutationFn: () => api.post<{ removed: number }>(`/transfers/clear?direction=${direction.value}`),
  onSuccess: (d) => {
    toast.success(t('transfers.cleared', d.removed), { description: t('transfers.clearedHint') })
    qc.invalidateQueries({ queryKey: ['transfers'] })
  },
})
</script>

<template>
  <div class="flex flex-col">
    <PageHeader :title="t('transfers.title')" :description="t('transfers.description')">
      <template #actions>
        <Button v-if="all.resume.length" variant="outline" size="sm" :disabled="working" @click="act(all.resume, 'resume')">
          <PlayIcon data-icon="inline-start" />
          {{ t('transfers.resumeAll') }}
        </Button>
        <Button v-if="all.pause.length" variant="outline" size="sm" :disabled="working" @click="act(all.pause, 'pause')">
          <PauseIcon data-icon="inline-start" />
          {{ t('transfers.pauseAll') }}
        </Button>
        <Button
          v-if="all.cancel.length"
          variant="ghost"
          size="sm"
          class="text-muted-foreground hover:text-destructive"
          :disabled="working"
          @click="askCancel(all.cancel)"
        >
          <XIcon data-icon="inline-start" />
          {{ t('transfers.cancelAll') }}
        </Button>
        <Button variant="ghost" size="sm" class="text-muted-foreground" @click="clear.mutate()">
          <BrushCleaningIcon data-icon="inline-start" />
          {{ t('transfers.clear') }}
        </Button>
      </template>
    </PageHeader>

    <div class="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <Tabs v-model="direction">
        <TabsList>
          <TabsTrigger value="download">
            <ArrowDownIcon />
            {{ t('transfers.downloads') }}
            <span class="ml-1 font-mono text-[11px] text-faint tnum">{{ speed(live.engine?.download_speed) }}</span>
          </TabsTrigger>
          <TabsTrigger value="upload">
            <ArrowUpIcon />
            {{ t('transfers.uploads') }}
            <span class="ml-1 font-mono text-[11px] text-faint tnum">{{ speed(live.engine?.upload_speed) }}</span>
          </TabsTrigger>
        </TabsList>
      </Tabs>
      <ToggleGroup v-model="filter" type="single" variant="outline" size="sm">
        <ToggleGroupItem value="active">
          {{ t('transfers.filters.active') }}
        </ToggleGroupItem>
        <ToggleGroupItem v-if="direction === 'download' && (stuckCount || filter === 'stuck')" value="stuck" class="data-[state=on]:text-warning">
          {{ t('transfers.filters.stuck') }}
          <span class="ml-1 font-mono text-[11px] tnum">{{ stuckCount }}</span>
        </ToggleGroupItem>
        <ToggleGroupItem value="done">
          {{ t('transfers.filters.done') }}
        </ToggleGroupItem>
        <ToggleGroupItem value="all">
          {{ t('common.all') }}
        </ToggleGroupItem>
      </ToggleGroup>
    </div>

    <!-- Selection bar: stays visible while scrolling long lists -->
    <div
      v-if="rows.length"
      class="sticky top-16 z-10 mb-4 flex min-h-11 flex-wrap items-center gap-2 rounded-xl border bg-background/90 px-4 py-1.5 backdrop-blur lg:top-3"
    >
      <label class="flex items-center gap-2.5 text-[12.5px] text-muted-foreground">
        <Checkbox :model-value="allState" @update:model-value="(v) => select(rows.map(x => x.id), v === true)" />
        {{ selection.length ? t('transfers.selected', selection.length) : t('transfers.selectAll') }}
      </label>
      <div v-if="selection.length" class="ml-auto flex flex-wrap items-center gap-1">
        <Button v-if="sel.resume.length" variant="ghost" size="sm" :disabled="working" @click="act(sel.resume, 'resume')">
          <PlayIcon data-icon="inline-start" />
          {{ t('common.resume') }} <span class="font-mono text-[11px] text-faint tnum">{{ sel.resume.length }}</span>
        </Button>
        <Button v-if="sel.pause.length" variant="ghost" size="sm" :disabled="working" @click="act(sel.pause, 'pause')">
          <PauseIcon data-icon="inline-start" />
          {{ t('common.pause') }} <span class="font-mono text-[11px] text-faint tnum">{{ sel.pause.length }}</span>
        </Button>
        <Button v-if="sel.retry.length" variant="ghost" size="sm" :disabled="working" @click="act(sel.retry, 'retry')">
          <RotateCcwIcon data-icon="inline-start" />
          {{ t('common.retry') }} <span class="font-mono text-[11px] text-faint tnum">{{ sel.retry.length }}</span>
        </Button>
        <Button
          v-if="sel.cancel.length"
          variant="ghost"
          size="sm"
          class="text-destructive hover:text-destructive"
          :disabled="working"
          @click="askCancel(sel.cancel)"
        >
          <XIcon data-icon="inline-start" />
          {{ t('common.cancel') }} <span class="font-mono text-[11px] tnum">{{ sel.cancel.length }}</span>
        </Button>
        <Button variant="ghost" size="sm" class="text-muted-foreground" @click="selected = new Set()">
          {{ t('transfers.deselect') }}
        </Button>
      </div>
    </div>

    <div v-if="isPending" class="flex flex-col gap-2">
      <Skeleton v-for="i in 4" :key="i" class="h-20 w-full" />
    </div>
    <div v-else-if="groups.length" class="flex flex-col gap-4">
      <section v-for="g in groups" :key="g.key" class="overflow-hidden rounded-xl bg-card">
        <header class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
          <div class="flex min-w-56 flex-1 items-center gap-3">
            <Checkbox
              :model-value="checkState(g.items)"
              :aria-label="t('transfers.selectFolder')"
              @update:model-value="(v) => select(g.items.map(x => x.id), v === true)"
            />
            <CoverArt v-if="g.album" :mbid="g.album.mbid" class="size-10 shrink-0" />
            <div v-else class="grid size-10 shrink-0 place-items-center rounded-[3px] bg-well text-faint ring-1 ring-border ring-inset">
              <FolderIcon class="size-4" :stroke-width="1.5" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="flex min-w-0 items-baseline gap-2">
                <RouterLink
                  v-if="g.album"
                  :to="{ name: 'album', params: { id: g.album.id } }"
                  class="truncate text-[13.5px] font-medium text-foreground hover:text-primary"
                >
                  {{ g.album.title }}
                </RouterLink>
                <span v-else class="truncate font-mono text-[13px] font-medium text-foreground" :title="g.dir">{{ g.folder }}</span>
                <span v-if="g.album" class="shrink-0 truncate text-[12.5px] text-muted-foreground">{{ g.album.artist }}</span>
              </p>
              <p class="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 font-mono text-[11.5px] text-faint tnum">
                <span v-if="g.tracks">{{ t('transfers.group.tracks', { n: g.done, total: g.tracks }) }}</span>
                <span v-else>{{ t('transfers.group.files', { n: g.current.filter(x => stateOf(x) === 'complete').length, total: g.current.length }) }}</span>
                <span aria-hidden="true">·</span>
                <span class="flex min-w-0 items-center gap-1">
                  {{ direction === 'download' ? t('transfer.from') : t('transfer.to') }}
                  <RouterLink
                    v-for="(p, i) in g.peers"
                    :key="p"
                    :to="{ name: 'peer', params: { username: p } }"
                    class="truncate text-muted-foreground hover:text-primary"
                  >{{ p }}{{ i < g.peers.length - 1 ? ',' : '' }}</RouterLink>
                </span>
                <template v-if="g.album && g.album.attempts > 1">
                  <span aria-hidden="true">·</span>
                  <span :class="g.album.attempts >= 5 && 'text-warning'" :title="t('transfers.group.attemptsHint')">{{ t('transfers.group.attempt', { n: g.album.attempts }) }}</span>
                </template>
              </p>
            </div>
          </div>
          <div class="ml-auto flex items-center gap-1">
            <Badge :variant="groupState(g).badge" class="mr-1 shrink-0">
              {{ groupState(g).label }}
            </Badge>
            <SwitchPeerMenu v-if="g.candidateId" :candidate-id="g.candidateId" :stuck="g.stuck" />
            <Tooltip v-if="possible(g.current).pause.length">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-sm" class="text-muted-foreground" :aria-label="t('transfers.pauseAll')" :disabled="working" @click="act(possible(g.current).pause, 'pause')">
                  <PauseIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('transfers.pauseAll') }}</TooltipContent>
            </Tooltip>
            <Tooltip v-if="possible(g.current).resume.length">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-sm" class="text-primary" :aria-label="t('transfers.resumeAll')" :disabled="working" @click="act(possible(g.current).resume, 'resume')">
                  <PlayIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('transfers.resumeAll') }}</TooltipContent>
            </Tooltip>
            <Tooltip v-if="possible(g.current).cancel.length">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-sm" class="text-muted-foreground hover:text-destructive" :aria-label="t('transfers.cancelAll')" :disabled="working" @click="askCancel(possible(g.current).cancel)">
                  <XIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('transfers.cancelAll') }}</TooltipContent>
            </Tooltip>
            <Button
              variant="ghost"
              size="icon-sm"
              class="text-muted-foreground"
              :aria-label="isOpen(g) ? t('transfers.group.hideFiles') : t('transfers.group.showFiles')"
              :aria-expanded="isOpen(g)"
              @click="toggle(g.key)"
            >
              <ChevronDownIcon :class="cn('transition-transform duration-200 motion-reduce:transition-none', isOpen(g) && 'rotate-180')" />
            </Button>
          </div>
        </header>
        <!-- The whole album at a glance, before its files -->
        <div v-if="g.active" class="mx-4 mb-3 h-[3px] overflow-hidden rounded-full bg-border">
          <div
            :class="cn('h-full rounded-full transition-[width] duration-500', g.stuck ? 'bg-warning' : 'bg-primary')"
            :style="{ width: `${g.pct}%` }"
          />
        </div>
        <div
          :class="cn('grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(0.2,0,0,1)] motion-reduce:transition-none',
                     isOpen(g) ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')"
        >
          <div class="min-h-0 overflow-hidden">
            <div class="flex flex-col divide-y border-t px-4">
              <TransferRow
                v-for="tr in [...g.current, ...(showOlder.has(g.key) ? g.older : [])]"
                :key="tr.id"
                :transfer="tr"
                :busy="busy.has(tr.id)"
                :peer="g.peers.length > 1 || !g.current.includes(tr)"
                :class="!g.current.includes(tr) && 'opacity-60'"
                selectable
                :selected="selected.has(tr.id)"
                @select="(id, on) => select([id], on)"
                @cancel="(id) => askCancel(g.items.filter(x => x.id === id))"
                @retry="(id) => run([id], 'retry')"
                @pause="(id) => run([id], 'pause')"
                @resume="(id) => run([id], 'resume')"
              />
            </div>
            <button
              v-if="g.older.length"
              type="button"
              class="flex w-full items-center gap-2 border-t px-4 py-2 text-left text-[12px] text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
              @click="toggleOlder(g.key)"
            >
              <HistoryIcon class="size-3.5" :stroke-width="1.5" />
              {{ showOlder.has(g.key) ? t('transfers.group.hideOlder') : t('transfers.group.showOlder', g.older.length) }}
            </button>
          </div>
        </div>
      </section>
    </div>
    <Empty v-else class="rounded-xl bg-card/50 py-14">
      <EmptyHeader>
        <EmptyTitle class="text-[14px]">
          {{ t(`transfers.empty.${direction}`) }}
        </EmptyTitle>
        <EmptyDescription class="text-[12.5px]">
          {{ t(`transfers.emptyHint.${direction}`) }}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>

    <AlertDialog v-model:open="confirmOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t('transfers.confirmTitle', toCancel.length) }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{ direction === 'download' ? t('transfers.confirmDownload') : t('transfers.confirmUpload') }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{{ t('transfers.keep') }}</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="doCancel">
            {{ t('transfers.confirmCancel') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>

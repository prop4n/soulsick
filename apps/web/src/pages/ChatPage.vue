<script setup lang="ts">
import type { ChatKind, ChatMessage, ChatOverview, ChatRoomInfo } from '@/lib/types'
import { FolderTreeIcon, HashIcon, LogOutIcon, MessageSquarePlusIcon, SendHorizontalIcon, Trash2Icon, UserRoundIcon, UsersRoundIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { ago, clock, dayLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'

/** Soulseek chat: private conversations and rooms. */
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const qc = useQueryClient()
const live = useLive()

const { data: overview, isPending } = useQuery({
  queryKey: ['chat-overview'],
  queryFn: () => api.get<ChatOverview>('/chat'),
})

// --- Current conversation (from the URL: ?with=user or ?room=name) ---------------
const current = computed<{ kind: ChatKind, target: string } | null>(() => {
  if (typeof route.query.with === 'string' && route.query.with)
    return { kind: 'private', target: route.query.with }
  if (typeof route.query.room === 'string' && route.query.room)
    return { kind: 'room', target: route.query.room }
  return null
})
function open(kind: ChatKind, target: string) {
  router.replace({ query: kind === 'private' ? { with: target } : { room: target } })
}
watch(current, c => (live.chatOpen = c), { immediate: true })
onUnmounted(() => (live.chatOpen = null))

const showMembers = ref(false)
const history = ref<ChatMessage[]>([])
const loading = ref(false)
const exhausted = ref(false)
async function load(before?: number) {
  const c = current.value
  if (!c)
    return
  loading.value = true
  try {
    const page = await api.get<ChatMessage[]>(`/chat/messages?${new URLSearchParams({ kind: c.kind, target: c.target, limit: '100', ...(before ? { before: String(before) } : {}) })}`)
    history.value = before ? [...page, ...history.value] : page
    exhausted.value = page.length < 100
  }
  finally {
    loading.value = false
  }
}

/** History + what arrived live since, without duplicates */
const messages = computed(() => {
  const c = current.value
  if (!c)
    return []
  const seen = new Set(history.value.map(m => m.id))
  const fresh = live.chat.filter(m => m.kind === c.kind && m.target === c.target && !seen.has(m.id) && m.id > (history.value.at(-1)?.id ?? 0))
  return [...history.value, ...fresh]
})
const days = computed(() => {
  const out: { day: string, items: ChatMessage[] }[] = []
  for (const m of messages.value) {
    const day = dayLabel(m.ts)
    const last = out.at(-1)
    if (last?.day === day)
      last.items.push(m)
    else out.push({ day, items: [m] })
  }
  return out
})

const box = ref<HTMLElement | null>(null)
const atBottom = ref(true)
function scrollDown() {
  nextTick(() => {
    if (box.value)
      box.value.scrollTop = box.value.scrollHeight
  })
}
function onScroll() {
  const el = box.value
  if (el)
    atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 60
}

/** Unread count of the open conversation: read as soon as it shows up */
const currentUnread = computed(() => {
  const c = current.value
  return c ? overview.value?.conversations.find(x => x.kind === c.kind && x.target === c.target)?.unread ?? 0 : 0
})
watch(currentUnread, (n) => {
  if (n && current.value && document.visibilityState === 'visible')
    api.post('/chat/read', current.value)
}, { immediate: true })

watch(current, async () => {
  history.value = []
  showMembers.value = false
  await load()
  scrollDown()
}, { immediate: true })

watch(() => messages.value.length, () => {
  if (atBottom.value)
    scrollDown()
})

// --- Sending ------------------------------------------------------------------------
const draft = ref('')
const send = useMutation({
  mutationFn: (text: string) => api.post<{ message: ChatMessage | null }>('/chat/send', { ...current.value, text }),
  onSuccess: (d) => {
    draft.value = ''
    if (d.message)
      history.value = [...history.value, d.message]
    atBottom.value = true
    scrollDown()
  },
  onError: e => toast.error(t('chat.sendFailed'), { description: e.message }),
})
function submit() {
  const text = draft.value.trim()
  if (text && current.value && !send.isPending.value)
    send.mutate(text)
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}

// --- New conversation, rooms ---------------------------------------------------------
const newUser = ref('')
function startPrivate() {
  const u = newUser.value.trim()
  if (u) {
    newUser.value = ''
    open('private', u)
  }
}

const roomsOpen = ref(false)
const roomFilter = ref('')
const { data: roomList, isFetching: roomsLoading, error: roomsError } = useQuery({
  queryKey: ['chat-rooms'],
  queryFn: () => api.get<ChatRoomInfo[]>('/chat/rooms'),
  enabled: roomsOpen,
  staleTime: 60_000,
  retry: false,
})
const shownRooms = computed(() => {
  const n = roomFilter.value.trim().toLowerCase()
  return (roomList.value ?? []).filter(r => !n || r.name.toLowerCase().includes(n)).slice(0, 200)
})
const join = useMutation({
  mutationFn: (room: string) => api.post('/chat/rooms/join', { room }),
  onSuccess: (_, room) => {
    roomsOpen.value = false
    roomFilter.value = ''
    qc.invalidateQueries({ queryKey: ['chat-overview'] })
    open('room', room)
  },
  onError: e => toast.error(e.message),
})
const leave = useMutation({
  mutationFn: (room: string) => api.post('/chat/rooms/leave', { room }),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['chat-overview'] })
    router.replace({ query: {} })
  },
})
const forget = useMutation({
  mutationFn: () => api.post('/chat/forget', current.value),
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ['chat-overview'] })
    router.replace({ query: {} })
  },
})

const { data: members, isFetching: membersLoading } = useQuery({
  queryKey: ['chat-members', computed(() => current.value?.target)],
  queryFn: () => api.get<string[]>(`/chat/rooms/users?room=${encodeURIComponent(current.value!.target)}`),
  enabled: computed(() => showMembers.value && current.value?.kind === 'room'),
  refetchInterval: 30_000,
})

const conversations = computed(() => overview.value?.conversations ?? [])
const isCurrent = (kind: ChatKind, target: string) => current.value?.kind === kind && current.value.target === target
const offline = computed(() => !live.engine?.connected)
</script>

<template>
  <div class="flex flex-col">
    <PageHeader :title="t('chat.title')" :description="t('chat.description')" />

    <div class="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <!-- Conversations -->
      <aside class="flex min-h-0 flex-col gap-3">
        <form class="flex gap-2" @submit.prevent="startPrivate">
          <InputGroup>
            <InputGroupAddon>
              <MessageSquarePlusIcon />
            </InputGroupAddon>
            <InputGroupInput v-model="newUser" :placeholder="t('chat.newPlaceholder')" class="font-mono" />
          </InputGroup>
        </form>
        <Button variant="outline" size="sm" class="justify-start" @click="roomsOpen = true">
          <HashIcon data-icon="inline-start" />
          {{ t('chat.joinRoom') }}
        </Button>

        <div v-if="isPending" class="flex flex-col gap-1.5">
          <Skeleton v-for="i in 5" :key="i" class="h-12 w-full" />
        </div>
        <nav v-else-if="conversations.length" class="flex flex-col gap-0.5 rounded-xl bg-card p-1.5">
          <button
            v-for="c in conversations"
            :key="`${c.kind}:${c.target}`"
            type="button"
            :class="cn('flex items-start gap-2.5 rounded-md px-2.5 py-2 text-left transition-colors',
                       isCurrent(c.kind, c.target) ? 'bg-accent' : 'hover:bg-accent/50')"
            @click="open(c.kind, c.target)"
          >
            <component :is="c.kind === 'room' ? HashIcon : UserRoundIcon" class="mt-0.5 size-3.5 shrink-0 text-faint" />
            <span class="flex min-w-0 flex-1 flex-col gap-0.5">
              <span class="flex items-baseline gap-2">
                <span :class="cn('truncate text-[13px]', c.unread && c.kind === 'private' ? 'font-semibold text-foreground' : 'text-foreground/90')">{{ c.target }}</span>
                <span v-if="c.last" class="ml-auto shrink-0 text-[10.5px] text-faint">{{ ago(c.last.ts) }}</span>
              </span>
              <span class="truncate text-[11.5px] text-muted-foreground">
                <template v-if="c.last">{{ c.last.outgoing || c.kind === 'room' ? `${t('chat.prefix', { user: c.last.outgoing ? t('chat.you') : c.last.username })} ` : '' }}{{ c.last.text }}</template>
                <template v-else>{{ t('chat.noMessageYet') }}</template>
              </span>
            </span>
            <span
              v-if="c.unread"
              :class="cn('mt-0.5 min-w-5 rounded-[4px] px-1 text-center font-mono text-[10.5px] leading-[18px] tnum',
                         c.kind === 'private' ? 'bg-primary/15 text-primary' : 'bg-border text-muted-foreground')"
            >{{ c.unread > 99 ? '99+' : c.unread }}</span>
          </button>
        </nav>
        <p v-else class="rounded-xl bg-card/50 px-4 py-6 text-[12.5px] text-faint">
          {{ t('chat.noConversation') }}
        </p>
      </aside>

      <!-- Thread -->
      <section v-if="current" class="flex min-w-0 flex-col overflow-hidden rounded-xl bg-card">
        <header class="flex items-center gap-2 border-b px-4 py-2.5">
          <component :is="current.kind === 'room' ? HashIcon : UserRoundIcon" class="size-4 text-faint" />
          <h2 class="min-w-0 truncate text-[14px] font-semibold">
            <RouterLink v-if="current.kind === 'private'" :to="{ name: 'peer', params: { username: current.target } }" class="hover:text-primary">
              {{ current.target }}
            </RouterLink>
            <template v-else>
              {{ current.target }}
            </template>
          </h2>
          <span class="text-[11.5px] text-faint">{{ current.kind === 'room' ? t('chat.room') : t('chat.private') }}</span>
          <div class="ml-auto flex items-center gap-0.5">
            <Tooltip v-if="current.kind === 'private'">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-sm" class="text-muted-foreground" as-child>
                  <RouterLink :to="{ name: 'browse', params: { username: current.target } }" :aria-label="t('chat.browse')">
                    <FolderTreeIcon />
                  </RouterLink>
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('chat.browse') }}</TooltipContent>
            </Tooltip>
            <Button
              v-if="current.kind === 'room'"
              variant="ghost"
              size="sm"
              :class="cn('text-muted-foreground', showMembers && 'bg-accent text-foreground')"
              @click="showMembers = !showMembers"
            >
              <UsersRoundIcon data-icon="inline-start" />
              {{ t('chat.members') }}
            </Button>
            <Tooltip v-if="current.kind === 'room'">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-sm" class="text-muted-foreground hover:text-destructive" :aria-label="t('chat.leave')" @click="leave.mutate(current.target)">
                  <LogOutIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('chat.leave') }}</TooltipContent>
            </Tooltip>
            <Tooltip v-else>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-sm" class="text-muted-foreground hover:text-destructive" :aria-label="t('chat.forget')" :disabled="!messages.length" @click="forget.mutate()">
                  <Trash2Icon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('chat.forget') }}</TooltipContent>
            </Tooltip>
          </div>
        </header>

        <div class="flex min-h-0 flex-1">
          <div
            ref="box"
            class="scrollbar-thin h-[calc(100svh-22rem)] min-h-72 flex-1 overflow-y-auto px-4 py-3"
            @scroll="onScroll"
          >
            <div v-if="!exhausted && messages.length >= 100" class="flex justify-center pb-3">
              <Button variant="ghost" size="xs" class="text-muted-foreground" :disabled="loading" @click="load(messages[0]?.id)">
                {{ t('activity.journal.older') }}
              </Button>
            </div>
            <p v-if="!messages.length && !loading" class="py-16 text-center text-[12.5px] text-faint">
              {{ current.kind === 'room' ? t('chat.emptyRoom') : t('chat.emptyPrivate', { user: current.target }) }}
            </p>
            <section v-for="d in days" :key="d.day" class="flex flex-col">
              <h3 class="legend py-2 text-center first-letter:uppercase">
                {{ d.day }}
              </h3>
              <div
                v-for="m in d.items"
                :key="m.id"
                class="group grid grid-cols-[3.25rem_minmax(0,1fr)] gap-x-3 py-[3px] text-[13px] leading-relaxed"
              >
                <time class="pt-[3px] font-mono text-[10.5px] text-faint tnum" :datetime="m.ts">{{ clock(m.ts).slice(0, 5) }}</time>
                <p class="min-w-0 break-words whitespace-pre-wrap">
                  <button
                    v-if="!m.outgoing && current.kind === 'room'"
                    type="button"
                    class="mr-1.5 font-mono text-[12px] font-medium text-muted-foreground hover:text-primary"
                    :title="t('chat.writeTo', { user: m.username })"
                    @click="open('private', m.username)"
                  >{{ m.username }}</button>
                  <span v-else :class="cn('mr-1.5 font-mono text-[12px] font-medium', m.outgoing ? 'text-primary' : 'text-muted-foreground')">{{ m.outgoing ? t('chat.you') : m.username }}</span>
                  <span class="text-foreground/90">{{ m.text }}</span>
                </p>
              </div>
            </section>
          </div>

          <!-- Room members -->
          <aside v-if="showMembers && current.kind === 'room'" class="scrollbar-thin hidden h-[calc(100svh-22rem)] min-h-72 w-52 shrink-0 overflow-y-auto border-l px-2 py-2 md:block">
            <p class="legend px-2 pb-1.5">
              {{ t('chat.membersCount', members?.length ?? 0) }}
            </p>
            <Spinner v-if="membersLoading && !members" class="mx-2" />
            <button
              v-for="u in members ?? []"
              :key="u"
              type="button"
              class="block w-full truncate rounded px-2 py-1 text-left font-mono text-[12px] text-muted-foreground hover:bg-accent hover:text-foreground"
              @click="open('private', u)"
            >
              {{ u }}
            </button>
          </aside>
        </div>

        <form class="flex items-end gap-2 border-t p-3" @submit.prevent="submit">
          <Textarea
            v-model="draft"
            rows="1"
            :maxlength="2000"
            :disabled="offline"
            :placeholder="offline ? t('chat.offline') : t('chat.placeholder', { target: current.target })"
            class="max-h-40 min-h-9 resize-none text-[13px]"
            @keydown="onKey"
          />
          <Button type="submit" size="icon" :disabled="!draft.trim() || send.isPending.value || offline" :aria-label="t('chat.send')">
            <Spinner v-if="send.isPending.value" />
            <SendHorizontalIcon v-else />
          </Button>
        </form>
      </section>

      <Empty v-else class="rounded-xl bg-card/50 py-20">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MessageSquarePlusIcon />
          </EmptyMedia>
          <EmptyTitle class="text-[14px]">
            {{ t('chat.pickTitle') }}
          </EmptyTitle>
          <EmptyDescription class="text-[12.5px]">
            {{ t('chat.pickHint') }}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>

    <!-- Join a room -->
    <Dialog v-model:open="roomsOpen">
      <DialogContent class="flex max-h-[85svh] flex-col gap-4 sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{{ t('chat.joinRoom') }}</DialogTitle>
          <DialogDescription>{{ t('chat.joinHint') }}</DialogDescription>
        </DialogHeader>
        <form class="flex gap-2" @submit.prevent="roomFilter.trim() && join.mutate(roomFilter.trim())">
          <InputGroup>
            <InputGroupAddon>
              <HashIcon />
            </InputGroupAddon>
            <InputGroupInput v-model="roomFilter" :placeholder="t('chat.roomPlaceholder')" autofocus />
          </InputGroup>
          <Button type="submit" :disabled="!roomFilter.trim() || join.isPending.value">
            {{ t('chat.join') }}
          </Button>
        </form>
        <div class="scrollbar-thin -mx-1 min-h-40 flex-1 overflow-y-auto px-1">
          <template v-if="roomsLoading && !roomList">
            <Skeleton v-for="i in 6" :key="i" class="mb-1 h-9 w-full" />
          </template>
          <p v-else-if="roomsError" class="py-6 text-center text-[12.5px] text-destructive">
            {{ roomsError.message }}
          </p>
          <button
            v-for="r in shownRooms"
            :key="r.name"
            type="button"
            :disabled="join.isPending.value || (overview?.rooms ?? []).includes(r.name)"
            class="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] hover:bg-accent disabled:opacity-50 disabled:hover:bg-transparent"
            @click="join.mutate(r.name)"
          >
            <HashIcon class="size-3.5 shrink-0 text-faint" />
            <span class="min-w-0 flex-1 truncate">{{ r.name }}</span>
            <span v-if="(overview?.rooms ?? []).includes(r.name)" class="text-[11px] text-success">{{ t('chat.joined') }}</span>
            <span class="font-mono text-[11px] text-faint tnum">{{ t('chat.users', r.users) }}</span>
          </button>
        </div>
      </DialogContent>
    </Dialog>
  </div>
</template>

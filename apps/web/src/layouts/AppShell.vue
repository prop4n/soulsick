<script setup lang="ts">
import type { Component } from 'vue'
import {
  ActivityIcon,
  ArrowLeftRightIcon,
  DiscIcon,
  FolderTreeIcon,
  HardDriveIcon,
  HouseIcon,
  LogOutIcon,
  MessagesSquareIcon,
  MenuIcon,
  SearchIcon,
  Settings2Icon,
  Share2Icon,
  UsersRoundIcon,
} from '@lucide/vue'
import { useQueryClient } from '@tanstack/vue-query'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import LibraryGuardBanner from '@/components/LibraryGuardBanner.vue'
import NetworkModule from '@/components/NetworkModule.vue'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useStatus } from '@/composables/queries'
import { ago } from '@/lib/format'
import { cn } from '@/lib/utils'
import { pageTitle } from '@/router'
import { useLive } from '@/stores/live'
import { useSession } from '@/stores/session'
import { useThemes } from '@/stores/theme'

interface NavItem { name: string, label: string, icon: Component, count?: number, tone?: 'warning' | 'signal', also?: string[] }

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const live = useLive()
const session = useSession()
const themes = useThemes()
const qc = useQueryClient()
const { data: status } = useStatus()

const navOpen = ref(false)

onMounted(() => {
  live.connect(qc)
  themes.load().catch(() => {})
})
onUnmounted(() => live.disconnect())
watch(locale, () => (document.title = pageTitle()))

const attention = computed(() => {
  const a = status.value?.albums ?? {}
  return (a.pending_approval ?? 0) + (a.needs_review ?? 0)
})

const groups = computed<{ label: string | null, items: NavItem[] }[]>(() => [
  {
    label: null,
    items: [{ name: 'home', label: t('nav.home'), icon: HouseIcon, count: attention.value, tone: 'warning' }],
  },
  {
    label: t('nav.groups.library'),
    items: [
      { name: 'artists', label: t('nav.artists'), icon: UsersRoundIcon, also: ['artist'] },
      { name: 'library', label: t('nav.albums'), icon: DiscIcon, also: ['album'] },
    ],
  },
  {
    label: t('nav.groups.soulseek'),
    items: [
      { name: 'search', label: t('nav.search'), icon: SearchIcon },
      {
        name: 'transfers',
        label: t('nav.transfers'),
        icon: ArrowLeftRightIcon,
        count: (status.value?.active_transfers.download ?? 0) + (status.value?.active_transfers.upload ?? 0),
        tone: 'signal',
      },
      { name: 'browse', label: t('nav.browse'), icon: FolderTreeIcon },
      { name: 'chat', label: t('nav.chat'), icon: MessagesSquareIcon, count: status.value?.chat_unread, tone: 'signal' },
      { name: 'shares', label: t('nav.shares'), icon: Share2Icon },
    ],
  },
  {
    label: t('nav.groups.system'),
    items: [
      { name: 'activity', label: t('nav.activity'), icon: ActivityIcon, count: live.unseenProblems, tone: 'warning' },
      { name: 'settings', label: t('nav.settings'), icon: Settings2Icon },
    ],
  },
])

function isActive(item: NavItem) {
  const r = route.name as string
  return r === item.name || !!item.also?.includes(r)
}

const hunterLine = computed(() => {
  const h = live.hunter ?? status.value?.hunter
  if (!h)
    return null
  if (h.current)
    return { active: true, text: h.current.step === 'search' ? t('common.quoted', { text: h.current.query }) : h.current.label }
  return { active: false, text: h.next_run_at ? t('shell.nextHunt', { when: ago(h.next_run_at) }) : t('shell.huntPaused') }
})

async function logout() {
  live.disconnect()
  await session.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex min-h-svh bg-background">
    <a
      href="#content"
      class="sr-only z-50 rounded-lg bg-primary px-3 py-2 text-[13px] text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
    >{{ t('shell.skip') }}</a>
    <!-- Sidebar: same background as the content, separated by a hairline -->
    <aside class="sticky top-0 hidden h-svh w-[240px] shrink-0 flex-col border-r lg:flex">
      <div class="flex h-14 items-center gap-2 px-5">
        <RouterLink :to="{ name: 'home' }" class="group flex items-baseline gap-1.5">
          <span class="font-serif text-[23px] leading-none italic tracking-tight text-foreground">soulsick</span>
          <span class="size-1.5 rounded-full bg-primary transition-shadow group-hover:shadow-[0_0_8px_var(--primary)]" />
        </RouterLink>
      </div>
      <nav class="scrollbar-thin flex flex-1 flex-col gap-5 overflow-y-auto px-3 pt-2 pb-4">
        <div v-for="(g, gi) in groups" :key="gi" class="flex flex-col gap-0.5">
          <p v-if="g.label" class="legend px-2 pb-1.5">
            {{ g.label }}
          </p>
          <RouterLink
            v-for="item in g.items"
            :key="item.name"
            :to="{ name: item.name }"
            :class="cn(
              'group relative flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors',
              isActive(item) ? 'bg-accent text-foreground' : 'text-muted-foreground hover:bg-accent/60 hover:text-foreground',
            )"
          >
            <span
              v-if="isActive(item)"
              class="absolute top-1.5 bottom-1.5 left-0 w-[2px] rounded-full bg-primary"
            />
            <component :is="item.icon" class="size-[15px] shrink-0" :stroke-width="1.75" />
            <span class="flex-1 truncate">{{ item.label }}</span>
            <span
              v-if="item.count"
              :class="cn(
                'min-w-5 rounded-[4px] px-1 text-center font-mono text-[10.5px] leading-[18px] tnum',
                item.tone === 'warning' ? 'bg-warning/15 text-warning' : 'bg-primary/12 text-primary',
              )"
            >{{ item.count }}</span>
          </RouterLink>
        </div>
      </nav>
      <div class="flex flex-col gap-3 border-t p-3">
        <div v-if="hunterLine" class="flex items-center gap-2 px-1 text-[11.5px]">
          <span :class="cn('size-1.5 shrink-0 rounded-full', hunterLine.active ? 'animate-pulse bg-primary' : 'bg-faint')" />
          <span :class="cn('truncate', hunterLine.active ? 'text-primary' : 'text-faint')">{{ hunterLine.text }}</span>
        </div>
        <RouterLink
          v-if="status && status.storage !== 'ok'"
          :to="{ name: 'settings', query: { tab: 'library' } }"
          :class="cn('flex items-center gap-2 rounded-md px-2 py-1.5 text-[11.5px]',
                     status.storage === 'critical' ? 'bg-destructive/10 text-destructive' : 'bg-warning/10 text-warning')"
        >
          <HardDriveIcon class="size-3.5 shrink-0" />
          {{ t(`storage.sidebar.${status.storage}`) }}
        </RouterLink>
        <NetworkModule />
        <div class="flex items-center justify-between gap-2 px-1">
          <span class="truncate text-[11.5px] text-faint">{{ session.state?.username }}</span>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button variant="ghost" size="icon-xs" class="text-faint hover:text-foreground" :aria-label="t('shell.logout')" @click="logout">
                <LogOutIcon />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{{ t('shell.logout') }}</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </aside>

    <!-- overflow-x-clip: cover halos bleed without creating horizontal scroll -->
    <div class="flex min-w-0 flex-1 flex-col overflow-x-clip">
      <header class="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur-md lg:hidden">
        <Button variant="ghost" size="icon-sm" :aria-label="t('shell.menu')" @click="navOpen = true">
          <MenuIcon />
        </Button>
        <span class="font-serif text-[20px] italic">soulsick</span>
      </header>

      <main id="content" tabindex="-1" class="mx-auto w-full max-w-[1320px] flex-1 px-4 py-7 outline-none sm:px-8">
        <LibraryGuardBanner v-if="status?.library_guard && !status.library_guard.ok" :guard="status.library_guard" />
        <RouterView v-slot="{ Component: page }">
          <component :is="page" :key="route.path" />
        </RouterView>
      </main>
    </div>

    <!-- Mobile navigation -->
    <Sheet v-model:open="navOpen">
      <SheetContent side="left" class="w-[260px] gap-0 p-0">
        <SheetHeader class="px-5 py-4">
          <SheetTitle class="font-serif text-[22px] font-normal italic">
            soulsick
          </SheetTitle>
          <SheetDescription class="sr-only">
            {{ t('shell.navigation') }}
          </SheetDescription>
        </SheetHeader>
        <nav class="flex flex-col gap-4 px-3 pb-4">
          <div v-for="(g, gi) in groups" :key="gi" class="flex flex-col gap-0.5">
            <p v-if="g.label" class="legend px-2 pb-1">
              {{ g.label }}
            </p>
            <RouterLink
              v-for="item in g.items"
              :key="item.name"
              :to="{ name: item.name }"
              :class="cn('flex h-9 items-center gap-2.5 rounded-md px-2 text-[13.5px]', isActive(item) ? 'bg-accent text-foreground' : 'text-muted-foreground')"
              @click="navOpen = false"
            >
              <component :is="item.icon" class="size-4" :stroke-width="1.75" />
              <span class="flex-1">{{ item.label }}</span>
              <span v-if="item.count" class="font-mono text-[11px] text-primary tnum">{{ item.count }}</span>
            </RouterLink>
          </div>
        </nav>
        <div class="mt-auto flex flex-col gap-2 border-t p-3">
          <NetworkModule />
          <Button variant="ghost" size="sm" class="justify-start text-muted-foreground" @click="logout">
            <LogOutIcon data-icon="inline-start" />
            {{ t('shell.logout') }}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>

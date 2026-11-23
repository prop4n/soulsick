<script setup lang="ts">
import type { Component } from 'vue'
import {
  ActivityIcon,
  ArrowLeftRightIcon,
  CompassIcon,
  DiscIcon,
  FolderTreeIcon,
  HardDriveIcon,
  HouseIcon,
  LogOutIcon,
  MenuIcon,
  MessagesSquareIcon,
  MoonIcon,
  PanelLeftIcon,
  SearchIcon,
  Settings2Icon,
  Share2Icon,
  SunIcon,
  UsersRoundIcon,
} from '@lucide/vue'
import { useQueryClient } from '@tanstack/vue-query'
import { useLocalStorage, useMutationObserver } from '@vueuse/core'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import LibraryGuardBanner from '@/components/LibraryGuardBanner.vue'
import NetworkModule from '@/components/NetworkModule.vue'
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useStatus } from '@/composables/queries'
import { ago } from '@/lib/format'
import { setTheme } from '@/lib/theme'
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
// Desktop: full sidebar or icon rail, remembered by this browser
const rail = useLocalStorage('soulsick-sidebar-rail', false)

onMounted(() => {
  live.connect(qc)
  themes.load().catch(() => {})
})
onUnmounted(() => live.disconnect())
watch(locale, () => (document.title = pageTitle()))

// Light or dark as shown right now (Settings can change it too)
const isDark = ref(document.documentElement.classList.contains('dark'))
useMutationObserver(document.documentElement, () => {
  isDark.value = document.documentElement.classList.contains('dark')
}, { attributes: true, attributeFilter: ['class'] })
const themeLabel = computed(() => (isDark.value ? t('shell.lightMode') : t('shell.darkMode')))
function toggleTheme() {
  setTheme(isDark.value ? 'light' : 'dark')
}

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
      { name: 'discover', label: t('nav.discover'), icon: CompassIcon },
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
        tone: status.value?.stuck_transfers ? 'warning' : 'signal',
      },
      { name: 'browse', label: t('nav.browse'), icon: FolderTreeIcon, also: ['peer'] },
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

// Breadcrumb: the section a detail page belongs to, then the page itself
const crumbs = computed(() => {
  const r = route.name as string
  const parent = groups.value.flatMap(g => g.items).find(i => i.also?.includes(r))
  const key = route.meta.title as string | undefined
  return { parent, page: key ? t(key) : '' }
})

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
  <div class="flex min-h-svh bg-background lg:h-svh lg:bg-well">
    <a
      href="#content"
      class="sr-only z-50 rounded-lg bg-primary px-3 py-2 text-[13px] text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
    >{{ t('shell.skip') }}</a>

    <!-- Sidebar: sits on the frame, the content is the inset panel next to it -->
    <!-- Both modes render the same rows: icons keep their column and only the width moves,
         so collapsing slides instead of jumping -->
    <aside
      :class="cn('sticky top-0 hidden h-svh shrink-0 flex-col overflow-hidden transition-[width] duration-200 ease-[cubic-bezier(0.2,0,0,1)] motion-reduce:transition-none lg:flex',
                 rail ? 'w-14' : 'w-[248px]')"
    >
      <div class="flex h-16 shrink-0 items-center px-5">
        <RouterLink :to="{ name: 'home' }" class="flex items-baseline rounded-md" aria-label="soulsick">
          <span class="font-serif text-[24px] leading-none italic text-foreground">s</span>
          <span
            :class="cn('overflow-hidden font-serif text-[24px] leading-none whitespace-nowrap italic text-foreground transition-[max-width,opacity] duration-200 motion-reduce:transition-none',
                       rail ? 'max-w-0 opacity-0' : 'max-w-28 opacity-100')"
            aria-hidden="true"
          >oulsick</span>
          <span class="ml-1.5 size-1.5 shrink-0 rounded-full bg-primary" />
        </RouterLink>
      </div>

      <nav class="scrollbar-thin flex flex-1 flex-col gap-6 overflow-x-hidden overflow-y-auto px-3 pb-4">
        <div v-for="(g, gi) in groups" :key="gi" class="flex flex-col gap-1">
          <div
            v-if="g.label"
            :class="cn('grid transition-[grid-template-rows,opacity] duration-200 motion-reduce:transition-none',
                       rail ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100')"
            :aria-hidden="rail"
          >
            <p class="overflow-hidden px-2 pb-1 text-[12px] font-medium whitespace-nowrap text-faint">
              {{ g.label }}
            </p>
          </div>
          <Tooltip v-for="item in g.items" :key="item.name" :disabled="!rail">
            <TooltipTrigger as-child>
              <RouterLink
                :to="{ name: item.name }"
                :aria-label="rail ? item.label : undefined"
                :class="cn(
                  'relative flex h-8 items-center gap-2 overflow-hidden rounded-md px-2 text-[13px] whitespace-nowrap transition-colors',
                  isActive(item) ? 'bg-primary/12 text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )"
              >
                <component :is="item.icon" class="size-4 shrink-0" :stroke-width="1.5" />
                <span class="flex-1 truncate">{{ item.label }}</span>
                <span
                  v-if="item.count && !rail"
                  :class="cn(
                    'min-w-5 rounded-[4px] px-1 text-center font-mono text-[11px] leading-[18px] tnum',
                    item.tone === 'warning' ? 'bg-warning/15 text-warning' : 'bg-primary/12 text-primary',
                  )"
                >{{ item.count }}</span>
                <span
                  v-else-if="item.count"
                  :class="cn('absolute top-1 left-6 size-1.5 rounded-full', item.tone === 'warning' ? 'bg-warning' : 'bg-primary')"
                />
              </RouterLink>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ item.label }}<template v-if="item.count">
                · {{ item.count }}
              </template>
            </TooltipContent>
          </Tooltip>
        </div>
      </nav>

      <!-- Footer, rail: one icon per line, the text in a tooltip. The two footers differ too much
         to share rows: the new one fades in once the width has moved -->
      <Transition
        enter-from-class="opacity-0"
        enter-active-class="transition-opacity duration-150 delay-150 motion-reduce:transition-none"
      >
        <div v-if="rail" class="flex w-14 shrink-0 flex-col items-center gap-1 p-3">
          <Tooltip v-if="hunterLine">
            <TooltipTrigger as-child>
              <span class="flex size-8 items-center justify-center" tabindex="0" :aria-label="hunterLine.text">
                <span :class="cn('size-1.5 rounded-full', hunterLine.active ? 'animate-pulse bg-primary' : 'bg-faint')" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ hunterLine.text }}
            </TooltipContent>
          </Tooltip>
          <Tooltip v-if="status && status.storage !== 'ok'">
            <TooltipTrigger as-child>
              <RouterLink
                :to="{ name: 'settings', query: { tab: 'library' } }"
                :aria-label="t(`storage.sidebar.${status.storage}`)"
                :class="cn('flex size-8 items-center justify-center rounded-md',
                           status.storage === 'critical' ? 'text-destructive' : 'text-warning')"
              >
                <HardDriveIcon class="size-4" :stroke-width="1.5" />
              </RouterLink>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ t(`storage.sidebar.${status.storage}`) }}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button variant="ghost" size="icon-sm" class="text-muted-foreground" :aria-label="themeLabel" @click="toggleTheme">
                <SunIcon v-if="isDark" class="size-4" :stroke-width="1.5" />
                <MoonIcon v-else class="size-4" :stroke-width="1.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ themeLabel }}
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button variant="ghost" size="icon-sm" class="text-muted-foreground" :aria-label="t('shell.logout')" @click="logout">
                <LogOutIcon class="size-4" :stroke-width="1.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ t('shell.logout') }} · {{ session.state?.username }}
            </TooltipContent>
          </Tooltip>
        </div>

        <div v-else class="flex w-[248px] shrink-0 flex-col gap-3 p-3">
          <div v-if="hunterLine" class="flex items-center gap-2 px-2 text-[12px]">
            <span :class="cn('size-1.5 shrink-0 rounded-full', hunterLine.active ? 'animate-pulse bg-primary' : 'bg-faint')" />
            <span :class="cn('truncate', hunterLine.active ? 'text-primary' : 'text-faint')">{{ hunterLine.text }}</span>
          </div>
          <RouterLink
            v-if="status && status.storage !== 'ok'"
            :to="{ name: 'settings', query: { tab: 'library' } }"
            :class="cn('flex items-center gap-2 rounded-md px-2 py-1.5 text-[12px]',
                       status.storage === 'critical' ? 'bg-destructive/10 text-destructive' : 'bg-warning/10 text-warning')"
          >
            <HardDriveIcon class="size-4 shrink-0" :stroke-width="1.5" />
            {{ t(`storage.sidebar.${status.storage}`) }}
          </RouterLink>
          <NetworkModule />
          <div class="flex flex-col gap-1">
            <button
              type="button"
              class="flex h-8 items-center gap-2 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              @click="toggleTheme"
            >
              <SunIcon v-if="isDark" class="size-4 shrink-0" :stroke-width="1.5" />
              <MoonIcon v-else class="size-4 shrink-0" :stroke-width="1.5" />
              {{ themeLabel }}
            </button>
            <button
              type="button"
              class="flex h-8 items-center gap-2 rounded-md px-2 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              @click="logout"
            >
              <LogOutIcon class="size-4 shrink-0" :stroke-width="1.5" />
              <span class="flex-1 text-left">{{ t('shell.logout') }}</span>
              <span class="truncate font-mono text-[11px] text-faint">{{ session.state?.username }}</span>
            </button>
          </div>
        </div>
      </Transition>
    </aside>

    <!-- Inset panel. Desktop: it scrolls inside itself (#scroller), so its margin and rounded
         corners stay put. Mobile: no frame, the window scrolls -->
    <div class="flex min-w-0 flex-1 flex-col lg:py-2 lg:pr-2">
      <div class="flex flex-1 flex-col bg-background lg:min-h-0 lg:overflow-hidden lg:rounded-xl lg:border">
        <header class="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background px-4 lg:static lg:h-12">
          <Button variant="ghost" size="icon-sm" class="text-muted-foreground lg:hidden" :aria-label="t('shell.menu')" @click="navOpen = true">
            <MenuIcon class="size-4" :stroke-width="1.5" />
          </Button>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button
                variant="ghost"
                size="icon-sm"
                class="hidden text-muted-foreground lg:inline-flex"
                :aria-label="rail ? t('shell.expand') : t('shell.collapse')"
                :aria-pressed="!rail"
                @click="rail = !rail"
              >
                <PanelLeftIcon class="size-4" :stroke-width="1.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{{ rail ? t('shell.expand') : t('shell.collapse') }}</TooltipContent>
          </Tooltip>
          <span class="h-4 w-px bg-border-strong" aria-hidden="true" />
          <Breadcrumb class="min-w-0 pl-1">
            <BreadcrumbList class="flex-nowrap gap-2 text-[13px] sm:gap-2">
              <template v-if="crumbs.parent">
                <BreadcrumbItem class="hidden sm:inline-flex">
                  <BreadcrumbLink as-child>
                    <RouterLink :to="{ name: crumbs.parent.name }">
                      {{ crumbs.parent.label }}
                    </RouterLink>
                  </BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator class="hidden sm:block" />
              </template>
              <BreadcrumbItem class="min-w-0">
                <BreadcrumbPage class="truncate">
                  {{ crumbs.page }}
                </BreadcrumbPage>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
        </header>

        <!-- overflow-x clipped: cover halos bleed without creating horizontal scroll -->
        <div id="scroller" class="scrollbar-thin flex flex-1 flex-col overflow-x-clip lg:min-h-0 lg:overflow-x-hidden lg:overflow-y-auto">
          <main id="content" tabindex="-1" class="mx-auto w-full max-w-[1320px] flex-1 px-4 pt-6 pb-12 outline-none sm:px-8">
            <LibraryGuardBanner v-if="status?.library_guard && !status.library_guard.ok" :guard="status.library_guard" />
            <RouterView v-slot="{ Component: page }">
              <component :is="page" :key="route.path" />
            </RouterView>
          </main>
        </div>
      </div>
    </div>

    <!-- Mobile navigation -->
    <Sheet v-model:open="navOpen">
      <SheetContent side="left" class="w-[264px] gap-0 bg-well p-0">
        <SheetHeader class="px-5 py-4">
          <SheetTitle class="flex items-baseline gap-1.5 font-serif text-[24px] font-normal italic">
            soulsick
            <span class="size-1.5 rounded-full bg-primary" />
          </SheetTitle>
          <SheetDescription class="sr-only">
            {{ t('shell.navigation') }}
          </SheetDescription>
        </SheetHeader>
        <nav class="flex flex-col gap-6 overflow-y-auto px-3 pb-4">
          <div v-for="(g, gi) in groups" :key="gi" class="flex flex-col gap-1">
            <p v-if="g.label" class="px-2 pb-1 text-[12px] font-medium text-faint">
              {{ g.label }}
            </p>
            <RouterLink
              v-for="item in g.items"
              :key="item.name"
              :to="{ name: item.name }"
              :class="cn('flex h-9 items-center gap-2 rounded-md px-2 text-[14px]', isActive(item) ? 'bg-primary/12 text-primary' : 'text-muted-foreground')"
              @click="navOpen = false"
            >
              <component :is="item.icon" class="size-4" :stroke-width="1.5" />
              <span class="flex-1">{{ item.label }}</span>
              <span v-if="item.count" class="font-mono text-[11px] text-primary tnum">{{ item.count }}</span>
            </RouterLink>
          </div>
        </nav>
        <div class="mt-auto flex flex-col gap-3 p-3">
          <NetworkModule />
          <div class="flex flex-col gap-1">
            <button type="button" class="flex h-9 items-center gap-2 rounded-md px-2 text-[14px] text-muted-foreground" @click="toggleTheme">
              <SunIcon v-if="isDark" class="size-4" :stroke-width="1.5" />
              <MoonIcon v-else class="size-4" :stroke-width="1.5" />
              {{ themeLabel }}
            </button>
            <button type="button" class="flex h-9 items-center gap-2 rounded-md px-2 text-[14px] text-muted-foreground" @click="logout">
              <LogOutIcon class="size-4" :stroke-width="1.5" />
              {{ t('shell.logout') }}
            </button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>

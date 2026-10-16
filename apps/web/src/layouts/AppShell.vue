<script setup lang="ts">
import type { Component } from 'vue'
import {
  ActivityIcon,
  ArrowLeftRightIcon,
  FolderTreeIcon,
  GaugeIcon,
  InboxIcon,
  LogOutIcon,
  MenuIcon,
  MoonIcon,
  ScrollTextIcon,
  SearchIcon,
  Settings2Icon,
  Share2Icon,
  SquareTerminalIcon,
  SunIcon,
  UsersRoundIcon,
} from '@lucide/vue'
import { useQueryClient } from '@tanstack/vue-query'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EventFeed from '@/components/EventFeed.vue'
import NetworkModule from '@/components/NetworkModule.vue'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useEvents, useStatus } from '@/composables/queries'
import { ago } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'
import { useSession } from '@/stores/session'

interface NavItem { name: string, label: string, icon: Component, count?: number, tone?: 'warning' | 'signal' }

const route = useRoute()
const router = useRouter()
const live = useLive()
const session = useSession()
const qc = useQueryClient()
const { data: status } = useStatus()
const { data: recent } = useEvents(ref({ limit: 80 }))

const activityOpen = ref(false)
const navOpen = ref(false)
const dark = ref(document.documentElement.classList.contains('dark'))

onMounted(() => live.connect(qc))
onUnmounted(() => live.disconnect())

const groups = computed<{ label: string, items: NavItem[] }[]>(() => [
  {
    label: 'Bibliothèque',
    items: [
      { name: 'home', label: 'Console', icon: GaugeIcon },
      { name: 'artists', label: 'Artistes', icon: UsersRoundIcon },
      { name: 'queue', label: 'File', icon: InboxIcon, count: status.value?.attention, tone: 'warning' },
    ],
  },
  {
    label: 'Réseau',
    items: [
      { name: 'search', label: 'Recherche', icon: SearchIcon },
      {
        name: 'transfers',
        label: 'Transferts',
        icon: ArrowLeftRightIcon,
        count: (status.value?.active_transfers.download ?? 0) + (status.value?.active_transfers.upload ?? 0),
        tone: 'signal',
      },
      { name: 'browse', label: 'Parcourir un pair', icon: FolderTreeIcon },
      { name: 'shares', label: 'Partages', icon: Share2Icon },
    ],
  },
  {
    label: 'Système',
    items: [
      { name: 'journal', label: 'Journal', icon: ScrollTextIcon },
      { name: 'logs', label: 'Logs en direct', icon: SquareTerminalIcon },
      { name: 'settings', label: 'Réglages', icon: Settings2Icon },
    ],
  },
])

function isActive(name: string) {
  const r = route.name as string
  if (name === 'artists')
    return r === 'artists' || r === 'artist' || r === 'album'
  return r === name
}

const events = computed(() => {
  const seen = new Set(live.events.map(e => e.id))
  return [...live.events, ...(recent.value ?? []).filter(e => !seen.has(e.id))].slice(0, 120)
})

const hunterLine = computed(() => {
  const h = live.hunter ?? status.value?.hunter
  if (!h)
    return null
  if (h.current)
    return { active: true, text: h.current.step === 'search' ? `« ${h.current.query} »` : h.current.label }
  return { active: false, text: h.next_run_at ? `Prochaine chasse ${ago(h.next_run_at)}` : 'Chasse en pause' }
})

function toggleTheme() {
  dark.value = !dark.value
  document.documentElement.classList.toggle('dark', dark.value)
  localStorage.setItem('soulsick-theme', dark.value ? 'dark' : 'light')
}

async function logout() {
  live.disconnect()
  await session.logout()
  router.push({ name: 'login' })
}

function openActivity() {
  activityOpen.value = true
  live.unseen = 0
}
</script>

<template>
  <div class="flex min-h-svh bg-background">
    <!-- Barre latérale : même fond que le contenu, séparée par un filet -->
    <aside class="sticky top-0 hidden h-svh w-[240px] shrink-0 flex-col border-r lg:flex">
      <div class="flex h-14 items-center gap-2 px-5">
        <RouterLink :to="{ name: 'home' }" class="wordmark rounded-[3px] bg-primary px-2 py-1 text-[13px] leading-none text-primary-foreground">
          soulsick
        </RouterLink>
      </div>
      <nav class="scrollbar-thin flex flex-1 flex-col gap-5 overflow-y-auto px-3 pt-2 pb-4">
        <div v-for="g in groups" :key="g.label" class="flex flex-col gap-0.5">
          <p class="legend px-2 pb-1.5">
            {{ g.label }}
          </p>
          <RouterLink
            v-for="item in g.items"
            :key="item.name"
            :to="{ name: item.name }"
            :class="cn(
              'group relative flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors',
              isActive(item.name) ? 'bg-foreground font-medium text-background' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
            )"
          >
            <component :is="item.icon" class="size-[15px] shrink-0" :stroke-width="1.75" />
            <span class="flex-1 truncate">{{ item.label }}</span>
            <span
              v-if="item.count"
              :class="cn(
                'min-w-5 rounded-[4px] px-1 text-center font-mono text-[10.5px] leading-[18px] tnum',
                item.tone === 'warning' ? 'bg-warning text-black' : 'bg-primary text-primary-foreground',
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
        <NetworkModule />
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur-md sm:px-6">
        <Button variant="ghost" size="icon-sm" class="lg:hidden" aria-label="Menu" @click="navOpen = true">
          <MenuIcon />
        </Button>
        <span class="wordmark rounded-[3px] bg-primary px-1.5 py-1 text-[12px] leading-none text-primary-foreground lg:hidden">soulsick</span>
        <div class="flex-1" />
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="sm" class="relative gap-2 text-muted-foreground" @click="openActivity">
              <ActivityIcon data-icon="inline-start" />
              <span class="hidden sm:inline">Activité</span>
              <span
                v-if="live.unseen"
                class="rounded-[3px] bg-primary px-1 font-mono text-[10.5px] leading-[16px] text-primary-foreground tnum"
              >{{ live.unseen > 99 ? '99+' : live.unseen }}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>Tout ce que Soulsick fait, en direct</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="Changer de thème" @click="toggleTheme">
              <SunIcon v-if="dark" />
              <MoonIcon v-else />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ dark ? 'Thème clair' : 'Thème sombre' }}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-sm" class="text-muted-foreground" aria-label="Se déconnecter" @click="logout">
              <LogOutIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Se déconnecter ({{ session.state?.username }})</TooltipContent>
        </Tooltip>
      </header>

      <main class="mx-auto w-full max-w-[1320px] flex-1 px-4 py-7 sm:px-8">
        <RouterView v-slot="{ Component: page }">
          <component :is="page" :key="route.fullPath" />
        </RouterView>
      </main>
    </div>

    <!-- Activité en direct -->
    <Sheet v-model:open="activityOpen">
      <SheetContent class="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader class="border-b px-5 py-4">
          <SheetTitle class="text-[15px]">
            Activité
          </SheetTitle>
          <SheetDescription class="text-[12.5px]">
            Chaque recherche, décision, transfert et déplacement de fichier.
          </SheetDescription>
        </SheetHeader>
        <div class="scrollbar-thin flex-1 overflow-y-auto px-5 pb-6">
          <EventFeed :events="events" compact />
        </div>
        <div class="border-t px-5 py-3">
          <Button variant="outline" size="sm" class="w-full" as-child @click="activityOpen = false">
            <RouterLink :to="{ name: 'journal' }">
              Ouvrir le journal complet
            </RouterLink>
          </Button>
        </div>
      </SheetContent>
    </Sheet>

    <!-- Navigation mobile -->
    <Sheet v-model:open="navOpen">
      <SheetContent side="left" class="w-[260px] gap-0 p-0">
        <SheetHeader class="px-5 py-4">
          <SheetTitle class="w-fit">
            <span class="wordmark rounded-[3px] bg-primary px-2 py-1 text-[13px] leading-none text-primary-foreground">soulsick</span>
          </SheetTitle>
          <SheetDescription class="sr-only">
            Navigation
          </SheetDescription>
        </SheetHeader>
        <nav class="flex flex-col gap-4 px-3 pb-4">
          <div v-for="g in groups" :key="g.label" class="flex flex-col gap-0.5">
            <p class="legend px-2 pb-1">
              {{ g.label }}
            </p>
            <RouterLink
              v-for="item in g.items"
              :key="item.name"
              :to="{ name: item.name }"
              :class="cn('flex h-9 items-center gap-2.5 rounded-md px-2 text-[13.5px]', isActive(item.name) ? 'bg-foreground font-medium text-background' : 'text-muted-foreground')"
              @click="navOpen = false"
            >
              <component :is="item.icon" class="size-4" :stroke-width="1.75" />
              <span class="flex-1">{{ item.label }}</span>
              <span v-if="item.count" class="font-mono text-[11px] text-primary tnum">{{ item.count }}</span>
            </RouterLink>
          </div>
        </nav>
        <div class="mt-auto border-t p-3">
          <NetworkModule />
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>

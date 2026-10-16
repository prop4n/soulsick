<script setup lang="ts">
import type { Activity, LogLine } from '@/lib/types'
import { ArrowDownToLineIcon, EraserIcon, PauseIcon, PlayIcon, SearchIcon } from '@lucide/vue'
import { useQuery } from '@tanstack/vue-query'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { api } from '@/lib/api'
import { speed } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'

/**
 * Logs techniques en direct : ce que le moteur fait réellement (connexions aux pairs,
 * réponses de recherche, transferts, MusicBrainz…). Le Journal, lui, raconte les décisions.
 */
const live = useLive()

const SOURCES = [
  { key: 'recherche', label: 'Recherches' },
  { key: 'soulseek', label: 'Réseau Soulseek' },
  { key: 'chasse', label: 'Chasse' },
  { key: 'import', label: 'Import' },
  { key: 'musicbrainz', label: 'MusicBrainz' },
  { key: 'journal', label: 'Journal' },
  { key: 'app', label: 'App' },
  { key: 'http', label: 'HTTP' },
  { key: 'web', label: 'Web' },
] as const

const sources = ref<string[]>(['recherche', 'soulseek', 'chasse', 'import', 'musicbrainz', 'journal', 'app'])
const level = ref<'info' | 'warning' | 'error'>('info')
const q = ref('')
const paused = ref(false)
const follow = ref(true)
const clearedAt = ref(0)
const frozen = ref<LogLine[] | null>(null)
const box = ref<HTMLElement | null>(null)

onMounted(async () => {
  const data = await api.get<{ logs: LogLine[] }>('/logs?limit=3000')
  live.seedLogs(data.logs)
  scrollDown()
})

const { data: activity } = useQuery({
  queryKey: ['activity'],
  queryFn: () => api.get<Activity>('/activity'),
  refetchInterval: 2000,
})

const RANK = { debug: 0, info: 1, warning: 2, error: 3, critical: 4 }
const lines = computed(() => {
  const all = frozen.value ?? live.logs
  const needle = q.value.trim().toLowerCase()
  const min = RANK[level.value]
  const out = all.filter(l =>
    l.id > clearedAt.value
    && sources.value.includes(l.source)
    && RANK[l.level] >= min
    && (!needle || l.message.toLowerCase().includes(needle) || l.logger.includes(needle)),
  )
  return out.slice(-1000)
})

function togglePause() {
  paused.value = !paused.value
  frozen.value = paused.value ? [...live.logs] : null
  if (!paused.value)
    scrollDown()
}

function scrollDown() {
  nextTick(() => {
    if (box.value)
      box.value.scrollTop = box.value.scrollHeight
  })
}

function onScroll() {
  const el = box.value
  if (el)
    follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

watch(() => lines.value.length, () => {
  if (follow.value && !paused.value)
    scrollDown()
})

function time(ts: string) {
  const d = new Date(ts)
  return `${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

const levelClass: Record<string, string> = {
  debug: 'text-faint',
  info: 'text-muted-foreground',
  warning: 'text-warning',
  error: 'text-destructive',
  critical: 'text-destructive',
}
const sourceClass: Record<string, string> = {
  recherche: 'text-primary',
  chasse: 'text-primary/80',
  soulseek: 'text-muted-foreground',
  import: 'text-success',
}
</script>

<template>
  <div class="flex flex-col">
    <PageHeader
      eyebrow="Système"
      title="Logs en direct"
      description="Le travail brut du moteur, ligne par ligne : réponses des pairs, connexions, transferts, requêtes MusicBrainz. Le Journal raconte les décisions ; ici, tu vois comment elles se font."
    />

    <!-- En ce moment -->
    <section class="mb-5 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 xl:grid-cols-4">
      <div class="flex flex-col gap-1.5 bg-card p-4">
        <span class="legend">Chasse</span>
        <span v-if="activity?.hunter.current" class="flex items-center gap-2 text-[12.5px] text-primary">
          <span class="size-1.5 animate-pulse rounded-full bg-primary" />
          <span class="truncate">{{ activity.hunter.current.step === 'search' ? `requête « ${activity.hunter.current.query} »` : activity.hunter.current.label }}</span>
        </span>
        <span v-else class="text-[12.5px] text-faint">au repos</span>
      </div>
      <div class="flex flex-col gap-1.5 bg-card p-4">
        <span class="legend">Recherches actives (60 s)</span>
        <template v-if="activity?.searches.length">
          <span v-for="s in activity.searches.slice(0, 3)" :key="s.ticket" class="flex items-baseline gap-2 text-[12.5px]">
            <span class="truncate">« {{ s.query }} »</span>
            <span class="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground tnum">{{ s.responses }} pairs · {{ s.files }} fichiers · {{ Math.round(s.age) }} s</span>
          </span>
        </template>
        <span v-else class="text-[12.5px] text-faint">aucune</span>
      </div>
      <div class="flex flex-col gap-1.5 bg-card p-4">
        <span class="legend">Transferts</span>
        <span class="font-mono text-[12.5px] tnum">
          ↓ {{ speed(live.engine?.download_speed) }} · ↑ {{ speed(live.engine?.upload_speed) }}
        </span>
        <span class="text-[11.5px] text-faint">{{ activity?.retrying ? `${activity.retrying} nouvel(s) essai(s) programmé(s)` : 'aucun essai en attente' }}</span>
      </div>
      <div class="flex flex-col gap-1.5 bg-card p-4">
        <span class="legend">Bibliothèque</span>
        <span :class="cn('text-[12.5px]', activity?.library_scanning ? 'text-primary' : 'text-faint')">
          {{ activity?.library_scanning ? 'analyse de /music en cours…' : 'au repos' }}
        </span>
      </div>
    </section>

    <!-- Filtres -->
    <div class="mb-3 flex flex-col gap-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center">
        <InputGroup class="lg:max-w-xs">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput v-model="q" placeholder="Filtrer (pseudo, fichier, requête…)" />
        </InputGroup>
        <ToggleGroup v-model="level" type="single" variant="outline" size="sm" class="justify-start">
          <ToggleGroupItem value="info">
            Tout
          </ToggleGroupItem>
          <ToggleGroupItem value="warning">
            Avertissements
          </ToggleGroupItem>
          <ToggleGroupItem value="error">
            Erreurs
          </ToggleGroupItem>
        </ToggleGroup>
        <div class="flex items-center gap-1.5 lg:ml-auto">
          <Button variant="outline" size="sm" @click="togglePause">
            <PlayIcon v-if="paused" data-icon="inline-start" />
            <PauseIcon v-else data-icon="inline-start" />
            {{ paused ? 'Reprendre' : 'Pause' }}
          </Button>
          <Button variant="ghost" size="sm" class="text-muted-foreground" @click="clearedAt = live.logs.at(-1)?.id ?? 0">
            <EraserIcon data-icon="inline-start" />
            Vider l’affichage
          </Button>
        </div>
      </div>
      <ToggleGroup v-model="sources" type="multiple" variant="outline" size="sm" class="flex-wrap justify-start">
        <ToggleGroupItem v-for="s in SOURCES" :key="s.key" :value="s.key">
          {{ s.label }}
        </ToggleGroupItem>
      </ToggleGroup>
    </div>

    <!-- Flux -->
    <div class="relative">
      <div
        ref="box"
        class="scrollbar-thin h-[calc(100svh-26rem)] min-h-80 overflow-y-auto rounded-lg border bg-well px-3 py-2 font-mono text-[11.5px] leading-[1.55]"
        @scroll="onScroll"
      >
        <div v-for="l in lines" :key="l.id" class="flex gap-3 border-b border-border/40 py-[3px] last:border-b-0">
          <span class="shrink-0 text-faint tnum">{{ time(l.ts) }}</span>
          <span :class="cn('w-11 shrink-0 uppercase', levelClass[l.level])">{{ l.level === 'warning' ? 'warn' : l.level }}</span>
          <span :class="cn('w-24 shrink-0 truncate', sourceClass[l.source] ?? 'text-faint')" :title="l.logger">{{ l.source }}</span>
          <span :class="cn('min-w-0 break-words', l.level === 'error' ? 'text-destructive' : 'text-foreground/85')">{{ l.message }}</span>
        </div>
        <p v-if="!lines.length" class="py-10 text-center font-sans text-[12.5px] text-faint">
          Rien pour ces filtres. Lance une recherche : chaque réponse de pair s’affichera ici.
        </p>
      </div>
      <Button
        v-if="!follow && !paused"
        size="sm"
        variant="secondary"
        class="absolute right-4 bottom-4 shadow-sm"
        @click="follow = true; scrollDown()"
      >
        <ArrowDownToLineIcon data-icon="inline-start" />
        Dernières lignes
      </Button>
    </div>
    <p class="mt-2 text-[11.5px] text-faint">
      {{ paused ? 'En pause — ' : '' }}{{ lines.length }} ligne(s) affichée(s) · les 3000 dernières sont gardées en mémoire (perdues au redémarrage).
    </p>
  </div>
</template>

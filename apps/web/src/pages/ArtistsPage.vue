<script setup lang="ts">
import { PlusIcon, SearchIcon, UsersRoundIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import AddArtistDialog from '@/components/AddArtistDialog.vue'
import CoverArt from '@/components/CoverArt.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useArtists } from '@/composables/queries'
import { cn } from '@/lib/utils'

const { data: artists, isPending } = useArtists()
const q = ref('')
const filter = ref<'all' | 'attention' | 'auto' | 'paused'>('all')
const addOpen = ref(false)

const list = computed(() => {
  const needle = q.value.trim().toLowerCase()
  return (artists.value ?? []).filter((a) => {
    if (needle && !a.name.toLowerCase().includes(needle))
      return false
    if (filter.value === 'attention')
      return a.stats.attention > 0
    if (filter.value === 'auto')
      return a.mode === 'auto'
    if (filter.value === 'paused')
      return !a.monitored
    return true
  })
})

function completion(a: { stats: { imported: number, monitored: number } }) {
  return a.stats.monitored ? a.stats.imported / a.stats.monitored : 0
}
</script>

<template>
  <div class="flex flex-col">
    <PageHeader
      eyebrow="Bibliothèque"
      title="Artistes suivis"
      description="Chaque artiste a son mode (automatique ou validation), son profil qualité et les types de sorties que tu veux."
    >
      <template #actions>
        <Button size="sm" @click="addOpen = true">
          <PlusIcon data-icon="inline-start" />
          Suivre un artiste
        </Button>
      </template>
    </PageHeader>

    <div class="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
      <InputGroup class="sm:max-w-xs">
        <InputGroupAddon>
          <SearchIcon />
        </InputGroupAddon>
        <InputGroupInput v-model="q" placeholder="Filtrer…" />
      </InputGroup>
      <ToggleGroup v-model="filter" type="single" variant="outline" size="sm" class="justify-start">
        <ToggleGroupItem value="all">
          Tous
        </ToggleGroupItem>
        <ToggleGroupItem value="attention">
          À traiter
        </ToggleGroupItem>
        <ToggleGroupItem value="auto">
          Automatiques
        </ToggleGroupItem>
        <ToggleGroupItem value="paused">
          En pause
        </ToggleGroupItem>
      </ToggleGroup>
      <span class="font-mono text-[11.5px] text-faint tnum sm:ml-auto">{{ list.length }} / {{ artists?.length ?? 0 }}</span>
    </div>

    <div v-if="isPending" class="grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      <div v-for="i in 10" :key="i" class="flex flex-col gap-2">
        <Skeleton class="aspect-square w-full" />
        <Skeleton class="h-4 w-2/3" />
      </div>
    </div>

    <Empty v-else-if="!artists?.length" class="rounded-lg border border-dashed py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <UsersRoundIcon />
        </EmptyMedia>
        <EmptyTitle>Aucun artiste suivi</EmptyTitle>
        <EmptyDescription>
          Ajoute un artiste depuis MusicBrainz : Soulsick récupère sa discographie et sait ce qui manque dans ta bibliothèque.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button size="sm" @click="addOpen = true">
          <PlusIcon data-icon="inline-start" />
          Suivre un artiste
        </Button>
      </EmptyContent>
    </Empty>

    <div v-else class="grid grid-cols-2 gap-x-5 gap-y-7 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      <RouterLink
        v-for="a in list"
        :key="a.id"
        :to="{ name: 'artist', params: { id: a.id } }"
        class="group flex flex-col gap-2.5"
      >
        <div class="relative">
          <CoverArt
            :mbid="a.stats.cover_mbid"
            :size="500"
            :alt="a.name"
            :class="cn('w-full transition-[filter,opacity] duration-300 group-hover:brightness-110', !a.monitored && 'opacity-50 grayscale')"
          />
          <span
            v-if="a.stats.attention"
            class="absolute top-2 right-2 rounded-[4px] bg-background/90 px-1.5 font-mono text-[10.5px] leading-[18px] text-warning ring-1 ring-warning/30 backdrop-blur tnum"
          >{{ a.stats.attention }} à traiter</span>
          <!-- Tranche : progression des albums suivis présents dans la bibliothèque -->
          <div class="absolute inset-x-0 bottom-0 h-[3px] bg-background/60">
            <div class="h-full bg-success/80" :style="{ width: `${completion(a) * 100}%` }" />
          </div>
        </div>
        <div class="flex min-w-0 flex-col gap-0.5">
          <span class="truncate text-[13.5px] font-medium group-hover:text-primary">{{ a.name }}</span>
          <div class="flex items-center gap-2 text-[11.5px] text-faint">
            <span class="font-mono tnum">{{ a.stats.imported }}/{{ a.stats.monitored }}</span>
            <span>rangés</span>
            <span class="ml-auto">{{ !a.monitored ? 'en pause' : a.mode === 'auto' ? 'auto' : 'validation' }}</span>
          </div>
        </div>
      </RouterLink>
    </div>

    <AddArtistDialog v-model:open="addOpen" />
  </div>
</template>

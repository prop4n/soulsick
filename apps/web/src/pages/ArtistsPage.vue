<script setup lang="ts">
import type { Artist } from '@/lib/types'
import { PlusIcon, SearchIcon, UsersRoundIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AddArtistDialog from '@/components/AddArtistDialog.vue'
import CoverArt from '@/components/CoverArt.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Toggle } from '@/components/ui/toggle'
import { useArtists } from '@/composables/queries'

const { t } = useI18n()
const { data: artists, isPending } = useArtists()
const q = ref('')
const attentionOnly = ref(false)
const addOpen = ref(false)

const list = computed(() => {
  const needle = q.value.trim().toLowerCase()
  return (artists.value ?? []).filter(a =>
    (!needle || a.name.toLowerCase().includes(needle)) && (!attentionOnly.value || a.stats.attention > 0))
})
/** Followed: their upcoming releases come on their own */
const followed = computed(() => list.value.filter(a => a.monitored))
/** Known through the albums on disk, not followed */
const library = computed(() => list.value.filter(a => !a.monitored))
const attention = computed(() => (artists.value ?? []).filter(a => a.stats.attention > 0).length)

function meta(a: Artist) {
  const parts = [t('artists.inLibrary', a.stats.imported ?? 0)]
  if (a.stats.wanted)
    parts.push(t('artists.onTheWay', a.stats.wanted))
  return parts.join(' · ')
}
</script>

<template>
  <div class="flex flex-col">
    <PageHeader :title="t('artists.title')" :description="t('artists.description')">
      <template #actions>
        <Button size="sm" @click="addOpen = true">
          <PlusIcon data-icon="inline-start" />
          {{ t('common.followArtist') }}
        </Button>
      </template>
    </PageHeader>

    <div class="mb-8 flex flex-col gap-3 sm:flex-row sm:items-center">
      <InputGroup class="sm:max-w-xs">
        <InputGroupAddon>
          <SearchIcon />
        </InputGroupAddon>
        <InputGroupInput v-model="q" :placeholder="t('common.filter')" />
      </InputGroup>
      <Toggle v-if="attention" v-model="attentionOnly" variant="outline" size="sm" class="w-fit">
        {{ t('artists.attention', attention) }}
      </Toggle>
    </div>

    <div v-if="isPending" class="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
      <div v-for="i in 10" :key="i" class="flex flex-col gap-2">
        <Skeleton class="aspect-square w-full" />
        <Skeleton class="h-4 w-2/3" />
      </div>
    </div>

    <Empty v-else-if="!artists?.length" class="rounded-xl bg-card py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <UsersRoundIcon />
        </EmptyMedia>
        <EmptyTitle>{{ t('artists.empty') }}</EmptyTitle>
        <EmptyDescription>
          {{ t('artists.emptyHint') }}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button size="sm" @click="addOpen = true">
          <PlusIcon data-icon="inline-start" />
          {{ t('common.followArtist') }}
        </Button>
      </EmptyContent>
    </Empty>

    <template v-else>
      <section class="flex flex-col gap-4">
        <div class="flex items-baseline gap-3">
          <h2 class="text-[16px] font-medium">
            {{ t('artists.followed') }}
          </h2>
          <span class="text-[12px] text-faint tnum">{{ followed.length }}</span>
        </div>
        <p v-if="!followed.length" class="text-[13px] text-muted-foreground">
          {{ q || attentionOnly ? t('artists.noMatch') : t('artists.noneFollowed') }}
        </p>
        <div v-else class="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-5">
          <RouterLink
            v-for="a in followed"
            :key="a.id"
            :to="{ name: 'artist', params: { id: a.id } }"
            class="group flex flex-col gap-3"
          >
            <div class="relative">
              <CoverArt
                :mbid="a.stats.cover_mbid"
                :size="500"
                :alt="a.name"
                class="w-full transition-[filter] duration-150 group-hover:brightness-110"
              />
              <span
                v-if="a.stats.attention"
                class="absolute top-2 right-2 rounded-[4px] bg-background/90 px-2 text-[12px] leading-5 text-warning tnum"
              >{{ t('artists.toHandle', { n: a.stats.attention }) }}</span>
            </div>
            <div class="flex min-w-0 flex-col gap-1">
              <span class="truncate text-[14px] font-medium group-hover:text-primary">{{ a.name }}</span>
              <span class="truncate text-[12px] text-faint tnum">{{ meta(a) }}</span>
            </div>
          </RouterLink>
        </div>
      </section>

      <section v-if="library.length" class="mt-12 flex flex-col gap-4">
        <div class="flex flex-col gap-1">
          <div class="flex items-baseline gap-3">
            <h2 class="text-[16px] font-medium">
              {{ t('artists.library') }}
            </h2>
            <span class="text-[12px] text-faint tnum">{{ library.length }}</span>
          </div>
          <p class="text-[13px] text-muted-foreground">
            {{ t('artists.libraryHint') }}
          </p>
        </div>
        <div class="grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-8">
          <RouterLink
            v-for="a in library"
            :key="a.id"
            :to="{ name: 'artist', params: { id: a.id } }"
            class="group flex flex-col gap-2"
          >
            <CoverArt :mbid="a.stats.cover_mbid" :size="250" :alt="a.name" class="w-full transition-[filter] duration-150 group-hover:brightness-110" />
            <div class="flex min-w-0 flex-col">
              <span class="truncate text-[13px] group-hover:text-primary">{{ a.name }}</span>
              <span class="truncate text-[12px] text-faint tnum">{{ t('artists.inLibrary', a.stats.imported ?? 0) }}</span>
            </div>
          </RouterLink>
        </div>
      </section>
    </template>

    <AddArtistDialog v-model:open="addOpen" />
  </div>
</template>

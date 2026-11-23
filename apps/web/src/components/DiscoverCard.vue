<script setup lang="ts">
import type { DeckCard, DiscoverProfile } from '@/lib/types'
import { CheckIcon, DownloadIcon } from '@lucide/vue'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import CoverArt from '@/components/CoverArt.vue'
import PreviewButton from '@/components/PreviewButton.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { artistPhotoUrl, coverUrl } from '@/lib/api'

/** One artist of the deck: who it is, why it is here, what to listen to and what to get. */
const props = defineProps<{
  card: DeckCard
  /** undefined while it is being asked, null when ListenBrainz knows nothing */
  profile: DiscoverProfile | null | undefined
  asked: Set<string>
}>()
const emit = defineEmits<{ get: [release: { mbid: string, title: string }] }>()
const { t } = useI18n()

const photoFailed = ref(false)
watch(() => props.card.mbid, () => (photoFailed.value = false))
const fallbackCover = computed(() => props.profile?.releases[0]?.mbid)

const facts = computed(() => {
  const p = props.profile
  if (!p)
    return []
  return [p.area, p.begin_year ? t('discover.since', { year: p.begin_year }) : null].filter(Boolean) as string[]
})
const preview = ref<InstanceType<typeof PreviewButton> | null>(null)
defineExpose({ togglePreview: () => preview.value?.toggle(), stopPreview: () => preview.value?.stop() })
</script>

<template>
  <article class="grid overflow-hidden rounded-2xl border bg-card md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
    <!-- The artist, large: their photo, or the cover of their best-known album -->
    <div class="relative aspect-square bg-muted md:aspect-auto md:min-h-[440px]">
      <img
        v-if="!photoFailed"
        :src="artistPhotoUrl(card.mbid)"
        :alt="card.name"
        class="absolute inset-0 size-full object-cover"
        draggable="false"
        @error="photoFailed = true"
      >
      <img
        v-else-if="fallbackCover"
        :src="coverUrl(fallbackCover, 500)"
        :alt="card.name"
        class="absolute inset-0 size-full object-cover"
        draggable="false"
      >
      <span v-else class="absolute inset-0 flex items-center justify-center font-serif text-[64px] text-muted-foreground">
        {{ card.name.slice(0, 1) }}
      </span>
    </div>

    <div class="flex min-w-0 flex-col gap-6 p-6">
      <div class="flex flex-col gap-2">
        <h2 class="font-serif text-[40px] leading-none tracking-tight text-balance">
          {{ card.name }}
        </h2>
        <p v-if="card.comment" class="text-[13px] text-muted-foreground">
          {{ card.comment }}
        </p>
        <Skeleton v-if="profile === undefined" class="h-4 w-2/3" />
        <template v-else-if="profile">
          <p v-if="facts.length" class="text-[13px] text-muted-foreground tnum">
            {{ facts.join(' · ') }}
          </p>
          <p v-if="profile.genres.length" class="text-[13px] text-faint">
            {{ profile.genres.join(', ') }}
          </p>
        </template>
      </div>

      <!-- Why it is here -->
      <p v-if="card.because.length" class="text-[14px] text-muted-foreground">
        {{ t('discover.close') }}
        <template v-for="(b, i) in card.because.slice(0, 3)" :key="b.id">
          <RouterLink :to="{ name: 'artist', params: { id: b.id } }" class="text-foreground hover:text-primary">{{ b.name }}</RouterLink><span v-if="i < Math.min(card.because.length, 3) - 1">, </span>
        </template>
        <span v-if="card.because.length > 3"> {{ t('discover.andMore', { n: card.because.length - 3 }) }}</span>
      </p>
      <p v-else-if="card.shelved" class="text-[14px] text-muted-foreground">
        {{ t('discover.shelved', card.shelved) }}
      </p>

      <!-- Its best-known releases, each to get -->
      <div v-if="profile === undefined" class="grid grid-cols-3 gap-4">
        <Skeleton v-for="i in 3" :key="i" class="aspect-square w-full" />
      </div>
      <ul v-else-if="profile?.releases.length" class="grid grid-cols-3 gap-4">
        <li v-for="r in profile.releases" :key="r.mbid" class="flex min-w-0 flex-col gap-2">
          <CoverArt :mbid="r.mbid" class="aspect-square w-full" :alt="r.title" />
          <div class="flex min-w-0 flex-col">
            <span class="truncate text-[13px]" :title="r.title">{{ r.title }}</span>
            <span class="text-[12px] text-faint tnum">{{ r.year ?? '' }}</span>
          </div>
          <span v-if="r.state === 'imported'" class="inline-flex h-6 items-center gap-1 text-[12px] text-muted-foreground">
            <CheckIcon class="size-3" />{{ t('discover.inLibrary') }}
          </span>
          <Button
            v-else-if="!asked.has(r.mbid) && r.state !== 'wanted'"
            variant="outline"
            size="xs"
            class="w-fit"
            @click="emit('get', r)"
          >
            <DownloadIcon data-icon="inline-start" />
            {{ t('album.get') }}
          </Button>
          <span v-else class="inline-flex h-6 items-center gap-1 text-[12px] text-success">
            <CheckIcon class="size-3" />{{ t('discover.asked') }}
          </span>
        </li>
      </ul>

      <PreviewButton v-if="profile?.track" ref="preview" :mbid="card.mbid" :title="profile.track.title" class="mt-auto" />
    </div>
  </article>
</template>

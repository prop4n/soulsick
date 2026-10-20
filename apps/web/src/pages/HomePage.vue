<script setup lang="ts">
import { ArrowRightIcon, PlusIcon, RadarIcon } from '@lucide/vue'
import { useMutation } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import AddArtistDialog from '@/components/AddArtistDialog.vue'
import AlbumRow from '@/components/AlbumRow.vue'
import PageHeader from '@/components/PageHeader.vue'
import StuckBanner from '@/components/StuckBanner.vue'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { useAlbums, useStatus } from '@/composables/queries'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * Home = the chain. Each stage is a tab listing its albums; the last one
 * ("In library") leads to the Albums page.
 */
type StageKey = 'wanted' | 'attention' | 'progress'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { data: status } = useStatus()
const addOpen = ref(false)

const STATUSES: Record<StageKey, string> = {
  wanted: 'wanted,failed',
  attention: 'pending_approval,needs_review',
  progress: 'searching,downloading,importing',
}

const counts = computed(() => {
  const a = status.value?.albums ?? {}
  return {
    wanted: (a.wanted ?? 0) + (a.failed ?? 0),
    attention: (a.pending_approval ?? 0) + (a.needs_review ?? 0),
    progress: (a.searching ?? 0) + (a.downloading ?? 0) + (a.importing ?? 0),
    library: a.imported ?? 0,
  }
})

function defaultStage(): StageKey {
  if (counts.value.attention)
    return 'attention'
  if (counts.value.progress)
    return 'progress'
  return 'wanted'
}

const stage = ref<StageKey>((route.query.stage as StageKey) in STATUSES ? route.query.stage as StageKey : 'attention')
// Without an explicit choice, open on the first stage that has something in it
const chosen = ref(!!route.query.stage)
watch(status, () => {
  if (!chosen.value && status.value)
    stage.value = defaultStage()
}, { immediate: true })

function pick(k: StageKey) {
  chosen.value = true
  stage.value = k
  router.replace({ query: { stage: k } })
}

const { data: albums, isPending } = useAlbums(computed(() => STATUSES[stage.value]))

const stages = computed(() => [
  { key: 'wanted' as const, n: counts.value.wanted, tone: 'text-foreground' },
  { key: 'attention' as const, n: counts.value.attention, tone: counts.value.attention ? 'text-warning' : 'text-foreground' },
  { key: 'progress' as const, n: counts.value.progress, tone: counts.value.progress ? 'text-primary' : 'text-foreground' },
])

const runHunt = useMutation({
  mutationFn: () => api.post<{ queued: number }>('/hunter/run'),
  onSuccess: d => toast.success(d.queued ? t('home.huntStarted', { n: d.queued }, d.queued) : t('home.nothingToHunt')),
  onError: e => toast.error(e.message),
})
</script>

<template>
  <div class="flex flex-col gap-6">
    <PageHeader :title="t('home.title')">
      <template #actions>
        <Button variant="outline" size="sm" :disabled="runHunt.isPending.value" @click="runHunt.mutate()">
          <RadarIcon data-icon="inline-start" />
          {{ t('home.huntNow') }}
        </Button>
        <Button size="sm" @click="addOpen = true">
          <PlusIcon data-icon="inline-start" />
          {{ t('common.followArtist') }}
        </Button>
      </template>
    </PageHeader>

    <StuckBanner />

    <!-- The chain: each stage is a tab -->
    <div role="tablist" :aria-label="t('home.chain')" class="grid grid-cols-2 overflow-hidden rounded-xl bg-card md:grid-cols-4">
      <button
        v-for="(s, i) in stages"
        :key="s.key"
        type="button"
        role="tab"
        :aria-selected="stage === s.key"
        :class="cn(
          'relative flex flex-col gap-3 p-5 text-left transition-colors',
          i > 0 && 'border-l', i >= 2 && 'max-md:border-t', i === 2 && 'max-md:border-l-0',
          stage === s.key ? 'bg-accent/70' : 'hover:bg-accent/35',
        )"
        @click="pick(s.key)"
      >
        <span v-if="stage === s.key" class="absolute inset-x-5 top-0 h-[2px] rounded-b-full bg-primary" />
        <span class="flex items-center gap-2">
          <span class="font-mono text-[10.5px] text-faint tnum">0{{ i + 1 }}</span>
          <span :class="cn('legend', stage === s.key ? '!text-foreground' : '!text-muted-foreground')">{{ t(`home.stages.${s.key}.label`) }}</span>
        </span>
        <span :class="cn('font-mono text-[34px] leading-none font-medium tracking-tight tnum', s.tone)">
          <Skeleton v-if="!status" class="h-8 w-14" />
          <template v-else>{{ s.n }}</template>
        </span>
        <span class="flex items-center gap-[3px]">
          <span
            v-for="j in 4"
            :key="j"
            :class="cn('h-1 flex-1 rounded-[1px]', j - 1 <= i ? 'bg-primary/70' : 'bg-border-strong')"
          />
        </span>
        <span class="text-[12px] text-faint">{{ t(`home.stages.${s.key}.hint`) }}</span>
      </button>
      <RouterLink
        :to="{ name: 'library' }"
        class="group relative flex flex-col gap-3 border-l p-5 transition-colors hover:bg-accent/35 max-md:border-t"
      >
        <span class="flex items-center gap-2">
          <span class="font-mono text-[10.5px] text-faint tnum">04</span>
          <span class="legend !text-muted-foreground">{{ t('home.stages.library.label') }}</span>
          <ArrowRightIcon class="ml-auto size-3.5 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
        </span>
        <span class="font-mono text-[34px] leading-none font-medium tracking-tight text-success tnum">
          <Skeleton v-if="!status" class="h-8 w-14" />
          <template v-else>{{ counts.library }}</template>
        </span>
        <span class="flex items-center gap-[3px]">
          <span v-for="j in 4" :key="j" class="h-1 flex-1 rounded-[1px] bg-success/70" />
        </span>
        <span class="text-[12px] text-faint">{{ t('home.stages.library.hint') }}</span>
      </RouterLink>
    </div>

    <section class="flex flex-col gap-3" role="tabpanel">
      <p class="text-[12.5px] text-muted-foreground">
        {{ t(`home.stages.${stage}.detail`) }}
      </p>
      <div v-if="isPending" class="flex flex-col gap-2">
        <Skeleton v-for="i in 4" :key="i" class="h-14 w-full" />
      </div>
      <div v-else-if="albums?.length" class="flex flex-col rounded-xl bg-card p-1.5">
        <AlbumRow v-for="a in albums" :key="a.id" :album="a" show-artist />
      </div>
      <Empty v-else class="rounded-xl bg-card/50 py-12">
        <EmptyHeader>
          <EmptyTitle class="text-[14px]">
            {{ t(`home.stages.${stage}.empty`) }}
          </EmptyTitle>
          <EmptyDescription v-if="stage === 'wanted'" class="text-[12.5px]">
            {{ t('home.wantedEmptyHint') }}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </section>

    <AddArtistDialog v-model:open="addOpen" />
  </div>
</template>

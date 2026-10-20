<script setup lang="ts">
import type { PeerAlternatives } from '@/lib/types'
import { ArrowLeftRightIcon, RadarIcon, StarIcon } from '@lucide/vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'
import { speed } from '@/lib/format'
import { cn } from '@/lib/utils'
import FormatTag from './FormatTag.vue'

/**
 * Replace a source that doesn't deliver: lists the other peers that have the tracks not received
 * yet (best first). What already arrived is kept.
 */
const props = withDefaults(defineProps<{ candidateId: number, stuck?: boolean, size?: 'xs' | 'sm' }>(), { stuck: false, size: 'xs' })
const { t } = useI18n()
const qc = useQueryClient()
const open = ref(false)

const { data, isPending } = useQuery({
  queryKey: computed(() => ['alternatives', props.candidateId]),
  queryFn: () => api.get<PeerAlternatives>(`/candidates/${props.candidateId}/alternatives`),
  enabled: open,
  staleTime: 0,
})

const working = ref<number | 'search' | null>(null)
async function choose(to: number | 'search') {
  working.value = to
  try {
    const body = to === 'search' ? { search: true } : { to }
    const r = await api.post<{ files: number }>(`/candidates/${props.candidateId}/switch`, body)
    toast.success(to === 'search' ? t('switchPeer.searching') : t('switchPeer.switched', r.files))
    open.value = false
    for (const key of ['transfers', 'album', 'albums', 'status'])
      qc.invalidateQueries({ queryKey: [key] })
  }
  catch (e) {
    toast.error((e as Error).message)
  }
  finally {
    working.value = null
  }
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <Button
        variant="ghost"
        :size="size"
        :class="cn(stuck ? 'text-warning hover:text-warning' : 'text-muted-foreground')"
        :title="t('switchPeer.hint')"
      >
        <ArrowLeftRightIcon data-icon="inline-start" />
        {{ t('switchPeer.button') }}
      </Button>
    </PopoverTrigger>
    <PopoverContent align="end" class="w-80 p-1.5">
      <p class="px-2.5 pt-1.5 pb-2 text-[12px] text-muted-foreground">
        <template v-if="isPending">
          {{ t('switchPeer.loading') }}
        </template>
        <template v-else-if="data?.alternatives.length">
          {{ t('switchPeer.intro', data.missing) }}
        </template>
        <template v-else>
          {{ t('switchPeer.none') }}
        </template>
      </p>
      <div v-if="isPending" class="flex justify-center py-3">
        <Spinner />
      </div>
      <button
        v-for="(a, i) in data?.alternatives ?? []"
        :key="a.candidate_id"
        type="button"
        :disabled="working !== null"
        class="flex w-full flex-col gap-1 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-accent disabled:opacity-60"
        @click="choose(a.candidate_id)"
      >
        <span class="flex items-center gap-2">
          <StarIcon v-if="i === 0" class="size-3.5 fill-primary text-primary" />
          <span class="min-w-0 truncate font-mono text-[12.5px] font-medium">{{ a.username }}</span>
          <FormatTag :format="a.format" />
          <span class="ml-auto font-mono text-[11px] text-muted-foreground tnum">{{ Math.round(a.score) }}/100</span>
          <Spinner v-if="working === a.candidate_id" class="size-3.5" />
        </span>
        <span class="flex flex-wrap items-center gap-x-2.5 font-mono text-[11px] text-faint tnum">
          <span :class="a.tracks >= (data?.missing ?? 0) && 'text-success'">{{ t('switchPeer.tracks', { n: a.tracks, total: data?.missing ?? 0 }) }}</span>
          <span :class="a.has_free_slots && 'text-success'">{{ a.has_free_slots ? t('switchPeer.freeSlot') : t('switchPeer.queue', { n: a.queue_size }) }}</span>
          <span v-if="a.avg_speed">{{ speed(a.avg_speed) }}</span>
        </span>
      </button>
      <div class="mt-1 border-t pt-1">
        <button
          type="button"
          :disabled="working !== null"
          class="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[12.5px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-60"
          @click="choose('search')"
        >
          <Spinner v-if="working === 'search'" class="size-3.5" />
          <RadarIcon v-else class="size-3.5" />
          {{ t('switchPeer.newSearch') }}
        </button>
      </div>
    </PopoverContent>
  </Popover>
</template>

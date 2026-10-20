<script setup lang="ts">
import type { ScoreDetail } from '@/lib/types'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { speed } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Explained score: three segments out of 100 (tracklist /50, format /30, peer /20).
 * Each segment shows what it earned out of what it could earn.
 */
const props = defineProps<{ detail: ScoreDetail, score: number, muted?: boolean }>()
const { t } = useI18n()

const parts = computed(() => [
  { key: 'match', label: t('score.tracklist'), got: props.detail.match?.points ?? 0, max: 50, cls: 'bg-primary' },
  { key: 'format', label: t('score.format'), got: props.detail.format?.points ?? 0, max: 30, cls: 'bg-primary/60' },
  { key: 'peer', label: t('score.peer'), got: props.detail.peer?.points ?? 0, max: 20, cls: 'bg-muted-foreground/60' },
])
</script>

<template>
  <div class="flex items-center gap-3">
    <span :class="cn('w-9 text-right font-mono text-[20px] leading-none font-medium tnum', muted ? 'text-faint' : 'text-foreground')">{{ Math.round(score) }}</span>
    <div class="flex flex-1 gap-[3px]">
      <Tooltip v-for="p in parts" :key="p.key">
        <TooltipTrigger as-child>
          <div class="flex flex-col gap-1" :style="{ flex: p.max }">
            <div class="h-1.5 overflow-hidden rounded-[1px] bg-border-strong/70">
              <div :class="cn('h-full', muted ? 'bg-faint/60' : p.cls)" :style="{ width: `${(p.got / p.max) * 100}%` }" />
            </div>
            <span class="legend !text-[9px] !tracking-[0.1em]">{{ p.label }} <span class="font-mono normal-case tnum">{{ Math.round(p.got) }}/{{ p.max }}</span></span>
          </div>
        </TooltipTrigger>
        <TooltipContent class="max-w-64">
          <template v-if="p.key === 'match' && detail.match">
            {{ t('score.matchDetail', { n: detail.match.tracks_matched, total: detail.match.tracks_expected, titles: Math.round(detail.match.title_score * 100) }) }}<template v-if="detail.match.duration_score != null">{{ t('score.durations', { pct: Math.round(detail.match.duration_score * 100) }) }}</template>.
            {{ t('coverage.edition', { title: detail.match.release }) }}
          </template>
          <template v-else-if="p.key === 'format' && detail.format">
            {{ detail.format.label }}<template v-if="detail.format.rank != null">
              — {{ t('score.rank', { n: detail.format.rank + 1 }) }}
            </template><template v-else>
              — {{ t('score.refused') }}
            </template><template v-if="detail.format.mixed">
              , {{ t('score.mixed') }}
            </template>
          </template>
          <template v-else-if="p.key === 'peer' && detail.peer">
            {{ detail.peer.free_slot ? t('peer.freeSlot') : t('peer.noFreeSlot') }}, {{ t('peer.queue', { n: detail.peer.queue_size }) }},
            {{ t('score.avgSpeed', { speed: speed(detail.peer.avg_speed) }) }}
          </template>
        </TooltipContent>
      </Tooltip>
    </div>
  </div>
</template>

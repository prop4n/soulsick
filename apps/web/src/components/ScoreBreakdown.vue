<script setup lang="ts">
import type { ScoreDetail } from '@/lib/types'
import { computed } from 'vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * Score expliqué : trois segments sur 100 (tracklist /50, format /30, pair /20).
 * Chaque segment montre ce qu'il a gagné sur ce qu'il pouvait gagner.
 */
const props = defineProps<{ detail: ScoreDetail, score: number, muted?: boolean }>()

const parts = computed(() => [
  { key: 'match', label: 'Tracklist', got: props.detail.match?.points ?? 0, max: 50, cls: 'bg-primary' },
  { key: 'format', label: 'Format', got: props.detail.format?.points ?? 0, max: 30, cls: 'bg-primary/60' },
  { key: 'peer', label: 'Pair', got: props.detail.peer?.points ?? 0, max: 20, cls: 'bg-muted-foreground/60' },
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
            {{ detail.match.tracks_matched }}/{{ detail.match.tracks_expected }} pistes reconnues,
            titres à {{ Math.round(detail.match.title_score * 100) }} %<template v-if="detail.match.duration_score != null">
              , durées à {{ Math.round(detail.match.duration_score * 100) }} %
            </template>.
            Édition : {{ detail.match.release }}
          </template>
          <template v-else-if="p.key === 'format' && detail.format">
            {{ detail.format.label }}<template v-if="detail.format.rank != null">
              — rang {{ detail.format.rank + 1 }} dans le profil
            </template><template v-else>
              — refusé par le profil
            </template><template v-if="detail.format.mixed">
              , formats mélangés
            </template>
          </template>
          <template v-else-if="p.key === 'peer' && detail.peer">
            {{ detail.peer.free_slot ? 'Slot libre' : 'Pas de slot libre' }}, file de {{ detail.peer.queue_size }},
            vitesse moyenne {{ Math.round(detail.peer.avg_speed / 1024) }} Ko/s
          </template>
        </TooltipContent>
      </Tooltip>
    </div>
  </div>
</template>

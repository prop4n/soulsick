<script setup lang="ts">
import type { AlbumStatus } from '@/lib/types'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { albumStatus, CHAIN_STAGES } from '@/lib/status'
import { cn } from '@/lib/utils'

/**
 * The chain: four meter-like segments (Wanted → Found → Received → Shelved).
 * Soulsick's signature: where an album stands, at a glance.
 */
const props = withDefaults(defineProps<{
  status: AlbumStatus
  size?: 'sm' | 'md' | 'lg'
  labels?: boolean
}>(), { size: 'sm', labels: false })

const { t } = useI18n()
const info = computed(() => albumStatus(props.status))

function segmentClass(i: number) {
  const { stage, tone } = info.value
  if (tone === 'off' || stage < 0)
    return 'bg-border-strong'
  if (tone === 'done')
    return 'bg-success'
  if (i < stage)
    return 'bg-primary/55'
  if (i === stage) {
    if (tone === 'active')
      return 'bg-primary animate-[pulse_1.6s_ease-in-out_infinite]'
    if (tone === 'attention')
      return 'bg-warning'
    if (tone === 'error')
      return 'bg-destructive'
    return 'bg-primary/80'
  }
  return 'bg-border-strong'
}

function labelClass(i: number) {
  const { stage, tone } = info.value
  if (tone === 'done')
    return 'text-success'
  if (i === stage)
    return tone === 'attention' ? 'text-warning' : tone === 'error' ? 'text-destructive' : 'text-primary'
  return i < stage ? 'text-muted-foreground' : 'text-faint'
}
</script>

<template>
  <div
    :class="cn('inline-flex flex-col', size === 'lg' ? 'gap-2' : 'gap-1')"
    :title="`${info.label} — ${info.hint}`"
    role="img"
    :aria-label="t('chain.stage', { label: info.label })"
  >
    <div :class="cn('flex', size === 'lg' ? 'gap-1' : 'gap-[3px]')">
      <span
        v-for="(_, i) in CHAIN_STAGES"
        :key="i"
        :class="cn(
          'rounded-[1px] transition-colors duration-300',
          size === 'sm' && 'h-[3px] w-3',
          size === 'md' && 'h-1 w-5',
          size === 'lg' && 'h-1.5 w-16 sm:w-20',
          segmentClass(i),
        )"
      />
    </div>
    <div v-if="labels" :class="cn('flex', size === 'lg' ? 'gap-1' : 'gap-[3px]')">
      <span
        v-for="(stage, i) in CHAIN_STAGES"
        :key="stage"
        :class="cn('legend !tracking-[0.1em]', size === 'lg' ? 'w-16 sm:w-20' : 'w-5', labelClass(i))"
      >{{ t(`chain.${stage}`) }}</span>
    </div>
  </div>
</template>

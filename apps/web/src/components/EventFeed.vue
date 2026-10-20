<script setup lang="ts">
import type { JournalEvent } from '@/lib/types'
import { computed } from 'vue'
import { dayLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import EventLine from './EventLine.vue'

/** Journal grouped by day, newest first. */
const props = withDefaults(defineProps<{ events: JournalEvent[], compact?: boolean, links?: boolean }>(), {
  compact: false,
  links: true,
})

const groups = computed(() => {
  const out: { day: string, items: JournalEvent[] }[] = []
  for (const e of props.events) {
    const day = dayLabel(e.ts)
    const last = out.at(-1)
    if (last && last.day === day)
      last.items.push(e)
    else out.push({ day, items: [e] })
  }
  return out
})
</script>

<template>
  <div class="flex flex-col">
    <section v-for="g in groups" :key="g.day" class="flex flex-col">
      <h3 :class="cn('legend px-1 pt-3 pb-1.5 first-letter:uppercase', !compact && 'sticky top-0 z-[1] -mx-1 bg-background/95 backdrop-blur')">
        {{ g.day }}
      </h3>
      <div class="flex flex-col divide-y divide-border/60">
        <EventLine v-for="e in g.items" :key="e.id" :event="e" :compact="compact" :links="links" />
      </div>
    </section>
  </div>
</template>

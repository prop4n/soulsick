<script setup lang="ts">
import type { JournalEvent } from '@/lib/types'
import { ChevronRightIcon } from '@lucide/vue'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { eventData, eventText } from '@/lib/serverText'
import { clock } from '@/lib/format'
import { eventFamilyLabel } from '@/lib/status'
import { cn } from '@/lib/utils'

/** A journal line: time, dot, family, message; raw data unfolds. */
const props = withDefaults(defineProps<{ event: JournalEvent, compact?: boolean, links?: boolean }>(), {
  compact: false,
  links: true,
})

const { t } = useI18n()
const open = ref(false)
const family = computed(() => props.event.kind.split('.')[0] ?? '')
const data = computed(() => eventData(props.event))
const hasData = computed(() => Object.keys(data.value).length > 0)
const dot = computed(() => ({
  info: family.value === 'import' && props.event.kind === 'import.done' ? 'bg-success' : 'bg-faint',
  warning: 'bg-warning',
  error: 'bg-destructive',
}[props.event.level]))
</script>

<template>
  <div :class="cn('group relative', compact ? 'py-1.5' : 'py-2')">
    <div class="flex items-baseline gap-3">
      <time class="shrink-0 font-mono text-[11px] text-faint tnum" :datetime="event.ts">{{ clock(event.ts) }}</time>
      <span :class="cn('relative top-[-1px] size-1.5 shrink-0 rounded-full', dot)" />
      <div class="min-w-0 flex-1">
        <p :class="cn('text-pretty', compact ? 'text-[12.5px] leading-snug' : 'text-[13px] leading-relaxed', event.level === 'error' ? 'text-destructive' : 'text-foreground/90')">
          <span v-if="!compact" class="legend mr-2 !text-[9.5px]">{{ eventFamilyLabel(family) }}</span>
          {{ eventText(event) }}
        </p>
        <div v-if="!compact && (hasData || (links && (event.release_group_id || event.artist_id)))" class="mt-0.5 flex items-center gap-3">
          <button
            v-if="hasData"
            type="button"
            class="inline-flex items-center gap-0.5 text-[11px] text-faint transition-colors hover:text-muted-foreground"
            @click="open = !open"
          >
            <ChevronRightIcon :class="cn('size-3 transition-transform', open && 'rotate-90')" />
            {{ t('events.details') }}
          </button>
          <RouterLink
            v-if="links && event.release_group_id"
            :to="{ name: 'album', params: { id: event.release_group_id } }"
            class="text-[11px] text-faint underline-offset-2 hover:text-primary hover:underline"
          >
            {{ t('events.viewAlbum') }}
          </RouterLink>
          <RouterLink
            v-else-if="links && event.artist_id"
            :to="{ name: 'artist', params: { id: event.artist_id } }"
            class="text-[11px] text-faint underline-offset-2 hover:text-primary hover:underline"
          >
            {{ t('events.viewArtist') }}
          </RouterLink>
        </div>
        <pre
          v-if="open"
          class="scrollbar-thin mt-2 max-h-72 overflow-auto rounded-md bg-well p-3 font-mono text-[11px] leading-relaxed text-muted-foreground ring-1 ring-border ring-inset"
        >{{ JSON.stringify(data, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

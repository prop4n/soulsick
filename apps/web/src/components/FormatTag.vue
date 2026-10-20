<script setup lang="ts">
import { computed } from 'vue'
import { cn } from '@/lib/utils'
import { FORMAT_LABELS, LOSSLESS } from '@/lib/status'

/** Audio format, printed like a label on a record spine. */
const props = defineProps<{ format: string | null | undefined, class?: string }>()
const lossless = computed(() => !!props.format && LOSSLESS.has(props.format))
</script>

<template>
  <span
    :class="cn(
      'inline-flex h-[18px] items-center rounded-[3px] border px-1.5 font-mono text-[10.5px] font-medium leading-none tnum',
      lossless ? 'border-primary/30 text-primary' : format ? 'border-border-strong text-muted-foreground' : 'border-dashed border-border-strong text-faint',
      props.class,
    )"
  >{{ format ? (FORMAT_LABELS[format] ?? format) : '?' }}</span>
</template>

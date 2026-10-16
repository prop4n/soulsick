<script setup lang="ts">
import { DiscIcon } from '@lucide/vue'
import { ref, watch } from 'vue'
import { coverUrl } from '@/lib/api'
import { cn } from '@/lib/utils'

const props = withDefaults(defineProps<{
  mbid?: string | null
  size?: 250 | 500 | 1200
  kind?: 'release-group' | 'release'
  alt?: string
  class?: string
}>(), { size: 250, kind: 'release-group', alt: '' })

const failed = ref(false)
const loaded = ref(false)
watch(() => props.mbid, () => {
  failed.value = false
  loaded.value = false
})
</script>

<template>
  <div :class="cn('relative aspect-square overflow-hidden rounded-[3px] bg-well ring-1 ring-border ring-inset', props.class)">
    <img
      v-if="mbid && !failed"
      :src="coverUrl(mbid, size, kind)"
      :alt="alt"
      loading="lazy"
      :class="cn('size-full object-cover transition-opacity duration-300', loaded ? 'opacity-100' : 'opacity-0')"
      @load="loaded = true"
      @error="failed = true"
    >
    <div v-if="!mbid || failed" class="absolute inset-0 grid place-items-center text-faint">
      <DiscIcon class="size-1/3 max-h-10 max-w-10" :stroke-width="1.25" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { coverUrl } from '@/lib/api'

/**
 * Album/artist ambience: the cover, huge and blurred, washed with its dominant colour and
 * fading into the page. Sits behind the header, across the whole content column.
 * The colour wash uses --cover-h / --cover-s (set by useCoverAccent on a parent).
 */
defineProps<{ mbid: string | null | undefined, tinted?: boolean }>()
</script>

<template>
  <div
    v-if="mbid"
    aria-hidden="true"
    class="pointer-events-none absolute -top-7 left-1/2 -z-10 h-[680px] w-screen -translate-x-1/2 overflow-hidden"
  >
    <img
      :src="coverUrl(mbid, 250)"
      alt=""
      class="absolute inset-0 size-full scale-125 object-cover opacity-45 blur-[70px] saturate-150 dark:opacity-75"
    >
    <!-- Dominant colour wash, strongest at the top -->
    <div
      v-if="tinted"
      class="absolute inset-0"
      style="background: linear-gradient(180deg, hsl(var(--cover-h) var(--cover-s) 32% / 0.55) 0%, hsl(var(--cover-h) var(--cover-s) 22% / 0.25) 45%, transparent 75%)"
    />
    <!-- Readability: darker behind the text on the left, then fade into the page -->
    <div class="absolute inset-0 bg-gradient-to-r from-background/70 via-background/25 to-background/45" />
    <div class="absolute inset-0 bg-gradient-to-b from-transparent via-background/45 to-background" />
  </div>
</template>

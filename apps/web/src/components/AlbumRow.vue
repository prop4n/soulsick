<script setup lang="ts">
import type { ReleaseGroup } from '@/lib/types'
import { year } from '@/lib/format'
import CoverArt from './CoverArt.vue'
import FormatTag from './FormatTag.vue'
import SignalChain from './SignalChain.vue'
import StatusBadge from './StatusBadge.vue'
import { serverText } from '@/lib/serverText'

/** Reusable album row: cover, title, chain, reason. */
defineProps<{ album: ReleaseGroup, showArtist?: boolean }>()
</script>

<template>
  <RouterLink
    :to="{ name: 'album', params: { id: album.id } }"
    class="group flex items-center gap-3.5 rounded-md px-2 py-2 transition-colors hover:bg-accent/50"
  >
    <CoverArt :mbid="album.mbid" class="size-11 shrink-0" :alt="album.title" />
    <div class="flex min-w-0 flex-1 flex-col gap-1">
      <div class="flex min-w-0 items-baseline gap-2">
        <span class="truncate text-[13.5px] font-medium text-foreground group-hover:text-primary">{{ album.title }}</span>
        <span class="shrink-0 font-mono text-[11px] text-faint tnum">{{ year(album.first_release_date) }}</span>
      </div>
      <p class="truncate text-[12px] text-muted-foreground">
        <template v-if="showArtist && album.artist">
          {{ album.artist.name }}<span class="text-faint"> · </span>
        </template>
        {{ serverText(album.status_reason, album.status_reason_t) }}
      </p>
    </div>
    <div class="hidden shrink-0 flex-col items-end gap-1.5 sm:flex">
      <div class="flex items-center gap-1.5">
        <FormatTag v-if="album.imported_format" :format="album.imported_format" />
        <StatusBadge :status="album.status" />
      </div>
      <SignalChain :status="album.status" />
    </div>
  </RouterLink>
</template>

<script setup lang="ts">
import type { AlbumStatus } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { ALBUM_STATUS } from '@/lib/status'

defineProps<{ status: AlbumStatus }>()
</script>

<template>
  <Badge :variant="ALBUM_STATUS[status].badge">
    {{ ALBUM_STATUS[status].label }}
  </Badge>
</template>

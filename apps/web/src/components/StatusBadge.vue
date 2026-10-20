<script setup lang="ts">
import type { AlbumStatus } from '@/lib/types'
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { albumStatus } from '@/lib/status'

const props = defineProps<{ status: AlbumStatus }>()
const info = computed(() => albumStatus(props.status))
</script>

<template>
  <Badge :variant="info.badge">
    {{ info.label }}
  </Badge>
</template>

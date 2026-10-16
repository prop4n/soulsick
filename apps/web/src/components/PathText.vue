<script setup lang="ts">
import { computed } from 'vue'
import { splitPath } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Chemin en mono : dossier atténué, nom de fichier lisible. Le chemin complet est sélectionnable. */
const props = defineProps<{ path: string | null | undefined, class?: string, dirOnly?: boolean }>()
const parts = computed(() => splitPath(props.path ?? ''))
</script>

<template>
  <span :class="cn('min-w-0 truncate font-mono text-[12px]', props.class)" :title="path ?? ''">
    <template v-if="dirOnly">
      <span class="text-muted-foreground">{{ path }}</span>
    </template>
    <template v-else>
      <span v-if="parts.dir" class="text-faint">{{ parts.dir }}/</span><span class="text-foreground">{{ parts.name }}</span>
    </template>
  </span>
</template>

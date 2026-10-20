<script setup lang="ts">
import type { ExistingGroup } from '@/lib/types'
import { CheckIcon, ChevronDownIcon, FolderIcon, ScanSearchIcon } from '@lucide/vue'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { ago, bytes, splitPath } from '@/lib/format'
import { cn } from '@/lib/utils'
import ExistingRow from './ExistingRow.vue'

/**
 * A manual download folder. Its files can be identified on MusicBrainz and shelved
 * in the library — even a single track of an album (the album then shows as partial).
 */
export interface ManualFolderInfo {
  dir: string
  username: string
  files: number
  size: number
  completed_at: string | null
  present: number
  shelved: number
  albums: number[]
}

const props = defineProps<{ folder: ManualFolderInfo }>()
const { t } = useI18n()
const open = ref(false)
const f = computed(() => props.folder)

const { data: group, isFetching } = useQuery({
  queryKey: ['existing', 'manual', computed(() => f.value.dir)],
  queryFn: () => api.get<ExistingGroup>(`/library/manual/folder?dir=${encodeURIComponent(f.value.dir)}`),
  enabled: open,
})
</script>

<template>
  <div class="flex flex-col py-2.5">
    <div class="flex items-center gap-3">
      <FolderIcon class="size-4 shrink-0 text-faint" :stroke-width="1.75" />
      <div class="flex min-w-0 flex-1 flex-col">
        <span class="truncate text-[13px]">{{ splitPath(f.dir).name }}</span>
        <span class="truncate font-mono text-[11px] text-faint" :title="f.dir">{{ f.dir }}</span>
      </div>
      <RouterLink :to="{ name: 'browse', params: { username: f.username } }" class="hidden font-mono text-[11.5px] text-muted-foreground hover:text-primary sm:inline">
        {{ f.username }}
      </RouterLink>
      <span class="font-mono text-[11.5px] text-muted-foreground tnum">{{ t('library.fileCount', f.files) }} · {{ bytes(f.size) }}</span>
      <span v-if="f.shelved" class="flex items-center gap-1 text-[11px] text-success">
        <CheckIcon class="size-3" />
        <RouterLink v-if="f.albums.length === 1" :to="{ name: 'album', params: { id: f.albums[0] } }" class="hover:underline">
          {{ t('library.shelvedCount', f.shelved) }}
        </RouterLink>
        <template v-else>{{ t('library.shelvedCount', f.shelved) }}</template>
      </span>
      <span v-if="f.files - f.present - f.shelved > 0" class="text-[11px] text-warning">{{ t('library.gone', f.files - f.present - f.shelved) }}</span>
      <span class="hidden w-24 text-right text-[11px] text-faint md:inline">{{ ago(f.completed_at) }}</span>
      <Button v-if="f.present" variant="outline" size="xs" @click="open = !open">
        <ScanSearchIcon data-icon="inline-start" />
        {{ t('library.identifyShelve') }}
        <ChevronDownIcon data-icon="inline-end" :class="cn('transition-transform', open && 'rotate-180')" />
      </Button>
    </div>
    <div v-if="open" class="mt-3">
      <Skeleton v-if="isFetching && !group" class="h-28 w-full" />
      <ExistingRow v-else-if="group && group.files" :group="group" />
      <p v-else class="text-[12px] text-faint">
        {{ t('library.nothingLeft') }}
      </p>
    </div>
  </div>
</template>

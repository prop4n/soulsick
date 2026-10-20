<script setup lang="ts">
import { ArrowUpIcon, FolderIcon } from '@lucide/vue'
import { useQuery } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'

/** Server folder browser (inside the container), to pick what to share. */
const { t } = useI18n()
const model = defineModel<string>({ required: true })
const path = ref(model.value || '/')

const { data, isFetching, error } = useQuery({
  queryKey: ['fs', path],
  queryFn: () => api.get<{ path: string, parent: string | null, dirs: string[] }>(`/fs?path=${encodeURIComponent(path.value)}`),
})

function enter(p: string) {
  path.value = p
  model.value = p
}
</script>

<template>
  <div class="flex flex-col overflow-hidden rounded-md border bg-well/60">
    <div class="flex items-center gap-2 border-b px-2 py-1.5">
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        :disabled="!data?.parent"
        :aria-label="t('folderPicker.parent')"
        @click="data?.parent && enter(data.parent)"
      >
        <ArrowUpIcon />
      </Button>
      <span class="min-w-0 truncate font-mono text-[12px] text-foreground">{{ data?.path ?? path }}</span>
    </div>
    <div class="scrollbar-thin h-56 overflow-y-auto p-1">
      <template v-if="isFetching && !data">
        <Skeleton v-for="i in 5" :key="i" class="mb-1 h-7 w-full" />
      </template>
      <p v-else-if="error" class="p-3 text-[12px] text-destructive">
        {{ error.message }}
      </p>
      <button
        v-for="d in data?.dirs ?? []"
        :key="d"
        type="button"
        class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[12px] text-muted-foreground hover:bg-accent hover:text-foreground"
        @click="enter(`${data!.path === '/' ? '' : data!.path}/${d}`)"
      >
        <FolderIcon class="size-3.5 shrink-0 text-faint" />
        <span class="truncate">{{ d }}</span>
      </button>
      <p v-if="data && !data.dirs.length" class="p-3 text-[12px] text-faint">
        {{ t('folderPicker.empty') }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { AppSettings, Share, SharePreview } from '@/lib/types'
import { EyeIcon, FolderPlusIcon, LibraryIcon, RefreshCwIcon, Trash2Icon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import FolderPicker from '@/components/FolderPicker.vue'
import PageHeader from '@/components/PageHeader.vue'
import TagInput from '@/components/TagInput.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { api } from '@/lib/api'
import { ago, bytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'
import { serverText } from '@/lib/serverText'

interface SharesResponse {
  shares: Share[]
  library: { path: string, shared: boolean }
  engine: { shared_folders: number, shared_files: number }
}

const { t } = useI18n()
const qc = useQueryClient()
const live = useLive()
const { data, isPending } = useQuery({ queryKey: ['shares'], queryFn: () => api.get<SharesResponse>('/shares') })

const normExt = (v: string) => v.trim().toLowerCase().replace(/^\./, '')

// Edit drafts per share
const drafts = reactive<Record<number, { enabled: boolean, allowed_extensions: string[], exclude_patterns: string[] }>>({})
watch(data, (d) => {
  for (const s of d?.shares ?? []) {
    drafts[s.id] = { enabled: s.enabled, allowed_extensions: [...s.allowed_extensions], exclude_patterns: [...s.exclude_patterns] }
  }
}, { immediate: true })

function dirty(s: Share) {
  const d = drafts[s.id]
  return !!d && JSON.stringify(d) !== JSON.stringify({ enabled: s.enabled, allowed_extensions: s.allowed_extensions, exclude_patterns: s.exclude_patterns })
}

const refresh = () => qc.invalidateQueries({ queryKey: ['shares'] })

const save = useMutation({
  mutationFn: (s: Share) => api.put(`/shares/${s.id}`, { path: s.path, ...drafts[s.id] }),
  onSuccess: () => {
    toast.success(t('shares.saved'), { description: t('shares.savedHint') })
    refresh()
  },
  onError: e => toast.error(e.message),
})
const remove = useMutation({
  mutationFn: (id: number) => api.del(`/shares/${id}`),
  onSuccess: refresh,
})
const rescan = useMutation({
  mutationFn: () => api.post('/shares/rescan'),
  onSuccess: () => toast.info(t('shares.rescanStarted')),
})

// Library sharing (global setting)
const toggleLibrary = useMutation({
  mutationFn: async (on: boolean) => {
    const s = await api.get<AppSettings>('/settings')
    s.soulseek.share_library = on
    return api.put('/settings', s)
  },
  onSuccess: refresh,
})

// Add
const addOpen = ref(false)
const newPath = ref('/')
const newExt = ref<string[]>([])
const newExclude = ref<string[]>([])
const add = useMutation({
  mutationFn: () => api.post('/shares', { path: newPath.value, allowed_extensions: newExt.value, exclude_patterns: newExclude.value }),
  onSuccess: () => {
    addOpen.value = false
    toast.success(t('shares.added'), { description: newPath.value })
    newExt.value = []
    newExclude.value = []
    refresh()
  },
  onError: e => toast.error(e.message),
})

// Preview
const previewFor = ref<Share | null>(null)
const { data: preview, isFetching: previewLoading } = useQuery({
  queryKey: ['share-preview', previewFor],
  queryFn: () => api.get<SharePreview>(`/shares/${previewFor.value!.id}/preview`),
  enabled: () => !!previewFor.value,
})
</script>

<template>
  <div class="flex flex-col">
    <PageHeader :title="t('shares.title')" :description="t('shares.description')">
      <template #actions>
        <Button variant="ghost" size="sm" class="text-muted-foreground" @click="rescan.mutate()">
          <RefreshCwIcon data-icon="inline-start" />
          {{ t('shares.rescan') }}
        </Button>
        <Button size="sm" @click="addOpen = true">
          <FolderPlusIcon data-icon="inline-start" />
          {{ t('shares.add') }}
        </Button>
      </template>
    </PageHeader>

    <!-- What the network actually sees -->
    <div class="mb-6 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-xl bg-card px-5 py-4">
      <div class="flex flex-col">
        <span class="legend">{{ t('shares.exposed') }}</span>
        <span class="font-mono text-[18px] tnum">{{ live.engine?.shared_files ?? data?.engine.shared_files ?? '—' }} <span class="text-[12px] text-faint">{{ t('shares.files') }}</span></span>
      </div>
      <div class="flex flex-col">
        <span class="legend">{{ t('shares.folders') }}</span>
        <span class="font-mono text-[18px] tnum">{{ live.engine?.shared_folders ?? data?.engine.shared_folders ?? '—' }}</span>
      </div>
      <p class="text-[12px] text-faint sm:ml-auto sm:max-w-xs">
        {{ t('shares.exposedHint') }}
      </p>
    </div>

    <div class="flex flex-col gap-3">
      <!-- The library -->
      <section class="flex flex-col gap-3 rounded-xl bg-card p-5 sm:flex-row sm:items-center">
        <LibraryIcon class="size-5 shrink-0 text-faint" :stroke-width="1.5" />
        <div class="flex min-w-0 flex-1 flex-col gap-0.5">
          <span class="text-[13.5px] font-medium">{{ t('shares.library') }}</span>
          <span class="truncate font-mono text-[12px] text-muted-foreground">{{ data?.library.path }}</span>
          <span class="text-[12px] text-faint">{{ t('shares.libraryHint') }}</span>
        </div>
        <label class="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Switch
            :model-value="data?.library.shared ?? false"
            :disabled="toggleLibrary.isPending.value"
            @update:model-value="(v: boolean) => toggleLibrary.mutate(v)"
          />
          {{ data?.library.shared ? t('shares.shared') : t('shares.notShared') }}
        </label>
      </section>

      <template v-if="isPending">
        <Skeleton v-for="i in 2" :key="i" class="h-40 w-full" />
      </template>

      <section
        v-for="s in data?.shares ?? []"
        :key="s.id"
        :class="cn('flex flex-col gap-4 rounded-xl bg-card p-5', !s.enabled && 'opacity-70')"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start">
          <div class="flex min-w-0 flex-1 flex-col gap-1">
            <div class="flex items-center gap-2">
              <span class="truncate font-mono text-[13px] font-medium">{{ s.path }}</span>
              <Badge v-if="!s.exists" variant="danger">
                {{ t('shares.missing') }}
              </Badge>
            </div>
            <p class="font-mono text-[11.5px] text-muted-foreground tnum">
              {{ t('shares.sharedFiles', s.file_count) }} · {{ bytes(s.total_size) }}
              <span :class="s.excluded_count ? 'text-warning' : 'text-faint'"> · {{ t('shares.excludedCount', { n: s.excluded_count }) }}</span>
              <span class="text-faint"> · {{ t('shares.indexed', { when: ago(s.last_scan_at) }) }}</span>
            </p>
          </div>
          <div class="flex items-center gap-2">
            <Button variant="ghost" size="sm" @click="previewFor = s">
              <EyeIcon data-icon="inline-start" />
              {{ t('shares.preview') }}
            </Button>
            <label class="flex items-center gap-2 text-[12.5px] text-muted-foreground">
              <Switch v-if="drafts[s.id]" v-model="drafts[s.id]!.enabled" />
              {{ t('shares.enabled') }}
            </label>
          </div>
        </div>
        <FieldGroup v-if="drafts[s.id]" class="grid gap-4 md:grid-cols-2">
          <Field>
            <FieldLabel class="legend">
              {{ t('shares.extensions') }}
            </FieldLabel>
            <TagInput v-model="drafts[s.id]!.allowed_extensions" mono :placeholder="t('shares.extensionsDefault')" :normalize="normExt" />
          </Field>
          <Field>
            <FieldLabel class="legend">
              {{ t('shares.excludes') }}
            </FieldLabel>
            <TagInput v-model="drafts[s.id]!.exclude_patterns" mono :placeholder="t('shares.excludesPlaceholder')" />
          </Field>
        </FieldGroup>
        <div class="flex items-center justify-between">
          <Button variant="ghost" size="sm" class="text-faint hover:text-destructive" @click="remove.mutate(s.id)">
            <Trash2Icon data-icon="inline-start" />
            {{ t('shares.unshare') }}
          </Button>
          <Button v-if="dirty(s)" size="sm" :disabled="save.isPending.value" @click="save.mutate(s)">
            {{ t('shares.saveRules') }}
          </Button>
        </div>
      </section>

      <Empty v-if="data && !data.shares.length" class="rounded-xl bg-card/50 py-10">
        <EmptyHeader>
          <EmptyTitle class="text-[14px]">
            {{ t('shares.emptyTitle') }}
          </EmptyTitle>
          <EmptyDescription class="text-[12.5px]">
            {{ t('shares.emptyHint') }}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    </div>

    <!-- Add -->
    <Dialog v-model:open="addOpen">
      <DialogContent class="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{{ t('shares.add') }}</DialogTitle>
          <DialogDescription>{{ t('shares.addHint') }}</DialogDescription>
        </DialogHeader>
        <FieldGroup>
          <Field>
            <FieldLabel>{{ t('shares.folder') }}</FieldLabel>
            <FolderPicker v-model="newPath" />
          </Field>
          <Field>
            <FieldLabel>{{ t('shares.extensions') }}</FieldLabel>
            <TagInput v-model="newExt" mono :placeholder="t('shares.extensionsPlaceholder')" :normalize="normExt" />
            <FieldDescription>{{ t('shares.extensionsHint') }}</FieldDescription>
          </Field>
          <Field>
            <FieldLabel>{{ t('shares.excludes') }}</FieldLabel>
            <TagInput v-model="newExclude" mono placeholder="*private*" />
          </Field>
        </FieldGroup>
        <DialogFooter>
          <Button :disabled="add.isPending.value || newPath === '/'" @click="add.mutate()">
            <Spinner v-if="add.isPending.value" data-icon="inline-start" />
            {{ t('shares.shareThis', { path: newPath }) }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Preview -->
    <Sheet :open="!!previewFor" @update:open="(o: boolean) => !o && (previewFor = null)">
      <SheetContent class="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
        <SheetHeader class="border-b px-5 py-4">
          <SheetTitle class="truncate font-mono text-[13px]">
            {{ previewFor?.path }}
          </SheetTitle>
          <SheetDescription class="text-[12.5px]">
            {{ t('shares.previewHint') }}
          </SheetDescription>
        </SheetHeader>
        <div class="scrollbar-thin flex flex-1 flex-col gap-5 overflow-y-auto px-5 py-4">
          <template v-if="previewLoading">
            <Skeleton v-for="i in 5" :key="i" class="h-8 w-full" />
          </template>
          <template v-else-if="preview">
            <div class="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border">
              <div class="flex flex-col bg-card p-3">
                <span class="legend">{{ t('shares.included') }}</span>
                <span class="font-mono text-[18px] text-success tnum">{{ preview.included }}</span>
                <span class="font-mono text-[11px] text-faint">{{ bytes(preview.included_size) }}</span>
              </div>
              <div class="flex flex-col bg-card p-3">
                <span class="legend">{{ t('shares.excluded') }}</span>
                <span class="font-mono text-[18px] text-warning tnum">{{ preview.excluded }}</span>
              </div>
            </div>
            <div class="flex flex-col gap-2">
              <span class="legend">{{ t('shares.byExtension') }}</span>
              <div class="flex flex-wrap gap-1.5">
                <span v-for="(n, ext) in preview.extensions" :key="ext" class="rounded-[4px] border px-1.5 py-0.5 font-mono text-[11px]">
                  .{{ ext }} <span class="text-faint tnum">{{ n }}</span>
                </span>
              </div>
            </div>
            <div v-if="preview.excluded_samples.length" class="flex flex-col gap-2">
              <span class="legend">{{ t('shares.excludedWhy') }}</span>
              <ul class="flex flex-col divide-y rounded-md border">
                <li v-for="x in preview.excluded_samples" :key="x.path" class="flex flex-col gap-0.5 px-3 py-2">
                  <span class="truncate font-mono text-[11.5px]" :title="x.path">{{ x.path }}</span>
                  <span class="text-[11.5px] text-warning">{{ serverText(x.reason, x.reason_t) }}</span>
                </li>
              </ul>
            </div>
          </template>
        </div>
      </SheetContent>
    </Sheet>
  </div>
</template>

<script setup lang="ts">
import type { ExistingGroup } from '@/lib/types'
import { FolderCheckIcon, RefreshCwIcon, ScanSearchIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import ExistingRow from '@/components/ExistingRow.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { api } from '@/lib/api'

/** Import music that is already on disk (e.g. downloaded with slskd): identify, tag, shelve. */
interface ExistingResponse {
  groups: ExistingGroup[]
  job: { running: boolean, done: number, total: number } | null
}

const { t } = useI18n()
const qc = useQueryClient()
const { data, isPending } = useQuery({
  queryKey: ['existing'],
  queryFn: () => api.get<ExistingResponse>('/library/existing'),
  refetchInterval: q => (q.state.data?.job?.running ? 3000 : false),
})

const filter = ref<'all' | 'todo' | 'safe' | 'check' | 'none'>('all')
const groups = computed(() => data.value?.groups ?? [])
const best = (g: ExistingGroup) => g.result?.proposals[0]
const counts = computed(() => ({
  all: groups.value.length,
  todo: groups.value.filter(g => !g.result).length,
  safe: groups.value.filter(g => best(g)?.safe).length,
  check: groups.value.filter(g => best(g) && !best(g)!.safe).length,
  none: groups.value.filter(g => g.result && !best(g)).length,
}))
const shown = computed(() => groups.value.filter((g) => {
  if (filter.value === 'todo')
    return !g.result
  if (filter.value === 'safe')
    return best(g)?.safe
  if (filter.value === 'check')
    return best(g) && !best(g)!.safe
  if (filter.value === 'none')
    return g.result && !best(g)
  return true
}).slice(0, 200))

const job = computed(() => data.value?.job)
const identifyAll = useMutation({
  mutationFn: () => api.post('/library/existing/identify-all'),
  onSuccess: () => {
    toast.info(t('import.identifyStarted'), { description: t('import.identifyStartedHint') })
    qc.invalidateQueries({ queryKey: ['existing'] })
  },
})
const rescan = useMutation({
  mutationFn: () => api.post('/library/scan'),
  onSuccess: () => toast.info(t('import.scanStarted')),
})

// Batch import of the safe matches
const confirmBatch = ref(false)
const batch = ref<{ done: number, total: number } | null>(null)
async function importSafe() {
  const safe = groups.value.filter(g => best(g)?.safe)
  batch.value = { done: 0, total: safe.length }
  let ok = 0
  for (const g of safe) {
    const p = best(g)!
    try {
      await api.post('/library/existing/apply', { dir: g.dir, release_group_mbid: p.release_group_mbid, release_mbid: p.release_mbid, follow: false })
      ok++
    }
    catch (e) {
      toast.error(`${g.dir}: ${(e as Error).message}`)
    }
    batch.value = { done: batch.value!.done + 1, total: safe.length }
  }
  batch.value = null
  toast.success(t('import.batchDone', ok))
  qc.invalidateQueries({ queryKey: ['existing'] })
}

const FILTERS = ['all', 'todo', 'safe', 'check', 'none'] as const
</script>

<template>
  <div class="flex flex-col">
    <div class="mb-5 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <p class="max-w-2xl text-[12.5px] text-muted-foreground text-pretty">
        {{ t('import.intro') }}
      </p>
      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" class="text-muted-foreground" :disabled="rescan.isPending.value" @click="rescan.mutate()">
          <RefreshCwIcon data-icon="inline-start" />
          {{ t('import.rescan') }}
        </Button>
        <Button variant="outline" size="sm" :disabled="!!job?.running || !counts.todo" @click="identifyAll.mutate()">
          <ScanSearchIcon data-icon="inline-start" />
          {{ t('import.identifyAll', { n: counts.todo }) }}
        </Button>
        <Button size="sm" :disabled="!counts.safe || !!batch" @click="confirmBatch = true">
          <FolderCheckIcon data-icon="inline-start" />
          {{ t('import.shelveSafe', { n: counts.safe }) }}
        </Button>
      </div>
    </div>

    <div v-if="job?.running || batch" class="mb-5 flex flex-col gap-2 rounded-xl bg-card p-4">
      <p class="text-[12.5px] text-muted-foreground">
        <template v-if="batch">
          {{ t('import.shelving', { done: batch.done, total: batch.total }) }}
        </template>
        <template v-else-if="job">
          {{ t('import.identifying', { done: job.done, total: job.total }) }}
        </template>
      </p>
      <Progress :model-value="batch ? (batch.done / Math.max(1, batch.total)) * 100 : ((job?.done ?? 0) / Math.max(1, job?.total ?? 1)) * 100" class="h-1" />
    </div>

    <ToggleGroup v-model="filter" type="single" variant="outline" size="sm" class="mb-4 flex-wrap justify-start">
      <ToggleGroupItem v-for="f in FILTERS" :key="f" :value="f">
        {{ t(`import.filters.${f}`) }} ({{ counts[f] }})
      </ToggleGroupItem>
    </ToggleGroup>

    <div v-if="isPending" class="flex flex-col gap-2">
      <Skeleton v-for="i in 4" :key="i" class="h-28 w-full" />
    </div>
    <div v-else-if="shown.length" class="flex flex-col gap-2">
      <ExistingRow v-for="g in shown" :key="g.dir" :group="g" />
      <p v-if="groups.length > 200" class="py-3 text-center text-[12px] text-faint">
        {{ t('import.capped', { total: groups.length }) }}
      </p>
    </div>
    <Empty v-else class="rounded-xl bg-card/50 py-14">
      <EmptyHeader>
        <EmptyTitle class="text-[14px]">
          {{ groups.length ? t('import.emptyFilter') : t('import.empty') }}
        </EmptyTitle>
        <EmptyDescription class="text-[12.5px]">
          {{ groups.length ? t('import.emptyFilterHint') : t('import.emptyHint') }}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>

    <AlertDialog v-model:open="confirmBatch">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t('import.confirmTitle', counts.safe) }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{ t('import.confirmBody') }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{{ t('common.cancel') }}</AlertDialogCancel>
          <AlertDialogAction @click="importSafe">
            {{ t('import.shelve') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>

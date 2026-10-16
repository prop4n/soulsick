<script setup lang="ts">
import { ArrowDownIcon, ArrowUpIcon, BrushCleaningIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'
import PageHeader from '@/components/PageHeader.vue'
import TransferRow from '@/components/TransferRow.vue'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useTransfers } from '@/composables/queries'
import { api } from '@/lib/api'
import { speed } from '@/lib/format'
import { useLive } from '@/stores/live'

const live = useLive()
const qc = useQueryClient()
const direction = ref<'download' | 'upload'>('download')
const filter = ref<'active' | 'done' | 'all'>('active')
const { data, isPending } = useTransfers(direction)

const ACTIVE = ['queued', 'initializing', 'transferring', 'paused']
const rows = computed(() => (data.value ?? []).filter((t) => {
  const state = live.transfers.get(t.id)?.state ?? t.state
  if (filter.value === 'active')
    return ACTIVE.includes(state)
  if (filter.value === 'done')
    return !ACTIVE.includes(state)
  return true
}))

/** Les transferts d'un même dossier distant sont regroupés : on lit un album, pas 12 lignes en vrac. */
const groups = computed(() => {
  const map = new Map<string, typeof rows.value>()
  for (const t of rows.value) {
    const dir = t.remote_path.replace(/\\/g, '/').split('/').slice(0, -1).join('/')
    const key = `${t.username}|${dir}`
    if (!map.has(key))
      map.set(key, [])
    map.get(key)!.push(t)
  }
  return [...map.entries()].map(([key, items]) => ({ key, username: key.split('|')[0], dir: key.split('|')[1], items }))
})

const busy = ref(new Set<number>())
const action = useMutation({
  mutationFn: ({ id, kind }: { id: number, kind: 'cancel' | 'retry' }) => {
    busy.value = new Set(busy.value).add(id)
    return api.post(`/transfers/${id}/${kind}`)
  },
  onSuccess: (_, v) => {
    toast.success(v.kind === 'retry' ? 'Nouvel essai lancé' : 'Transfert annulé', {
      description: v.kind === 'retry' ? 'Le fichier est redemandé au pair ; suis son état sur cette ligne.' : undefined,
    })
    qc.invalidateQueries({ queryKey: ['transfers'] })
  },
  onError: e => toast.error(e.message),
  onSettled: (_, __, v) => {
    const next = new Set(busy.value)
    next.delete(v.id)
    busy.value = next
  },
})
const clear = useMutation({
  mutationFn: () => api.post<{ removed: number }>(`/transfers/clear?direction=${direction.value}`),
  onSuccess: (d) => {
    toast.success(`${d.removed} transfert(s) retiré(s) de la liste`, { description: 'Leur trace reste dans le journal.' })
    qc.invalidateQueries({ queryKey: ['transfers'] })
  },
})
</script>

<template>
  <div class="flex flex-col">
    <PageHeader
      eyebrow="Réseau"
      title="Transferts"
      description="Ce que tu reçois, ce que les autres prennent chez toi : pair, fichier distant, destination locale et état, en direct."
    >
      <template #actions>
        <Button variant="ghost" size="sm" class="text-muted-foreground" @click="clear.mutate()">
          <BrushCleaningIcon data-icon="inline-start" />
          Retirer les terminés
        </Button>
      </template>
    </PageHeader>

    <div class="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <Tabs v-model="direction">
        <TabsList>
          <TabsTrigger value="download">
            <ArrowDownIcon />
            Réception
            <span class="ml-1 font-mono text-[11px] text-faint tnum">{{ speed(live.engine?.download_speed) }}</span>
          </TabsTrigger>
          <TabsTrigger value="upload">
            <ArrowUpIcon />
            Envoi
            <span class="ml-1 font-mono text-[11px] text-faint tnum">{{ speed(live.engine?.upload_speed) }}</span>
          </TabsTrigger>
        </TabsList>
      </Tabs>
      <ToggleGroup v-model="filter" type="single" variant="outline" size="sm">
        <ToggleGroupItem value="active">
          En cours
        </ToggleGroupItem>
        <ToggleGroupItem value="done">
          Terminés
        </ToggleGroupItem>
        <ToggleGroupItem value="all">
          Tout
        </ToggleGroupItem>
      </ToggleGroup>
    </div>

    <div v-if="isPending" class="flex flex-col gap-2">
      <Skeleton v-for="i in 4" :key="i" class="h-20 w-full" />
    </div>
    <div v-else-if="groups.length" class="flex flex-col gap-4">
      <section v-for="g in groups" :key="g.key" class="rounded-lg border bg-card">
        <header class="flex items-center gap-2 border-b px-4 py-2.5">
          <RouterLink :to="{ name: 'browse', params: { username: g.username } }" class="font-mono text-[12px] font-medium hover:text-primary">
            {{ g.username }}
          </RouterLink>
          <span class="min-w-0 truncate font-mono text-[11.5px] text-faint" :title="g.dir">{{ g.dir }}</span>
          <span class="ml-auto font-mono text-[11px] text-faint tnum">{{ g.items.length }}</span>
        </header>
        <div class="flex flex-col divide-y px-4">
          <TransferRow
            v-for="t in g.items"
            :key="t.id"
            :transfer="t"
            :busy="busy.has(t.id)"
            @cancel="(id) => action.mutate({ id, kind: 'cancel' })"
            @retry="(id) => action.mutate({ id, kind: 'retry' })"
          />
        </div>
      </section>
    </div>
    <Empty v-else class="rounded-lg border border-dashed py-14">
      <EmptyHeader>
        <EmptyTitle class="text-[14px]">
          {{ direction === 'download' ? 'Rien en réception' : 'Personne ne télécharge chez toi en ce moment' }}
        </EmptyTitle>
        <EmptyDescription class="text-[12.5px]">
          {{ direction === 'download'
            ? 'Les téléchargements lancés par la chasse ou à la main apparaissent ici.'
            : 'Les demandes des autres pairs sur tes dossiers partagés apparaissent ici, avec le fichier exact envoyé.' }}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  </div>
</template>

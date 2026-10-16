<script setup lang="ts">
import type { SearchSnapshot } from '@/lib/types'
import { SearchIcon } from '@lucide/vue'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { useIntervalFn } from '@vueuse/core'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import FolderResult from '@/components/FolderResult.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useStatus } from '@/composables/queries'
import { api } from '@/lib/api'
import { LOSSLESS } from '@/lib/status'

const route = useRoute()
const router = useRouter()
const { data: status } = useStatus()

const q = ref((route.query.q as string) ?? '')
const ticket = ref<number | null>(route.query.t ? Number(route.query.t) : null)
const startedAt = ref(Date.now())
const quality = ref<'all' | 'lossless' | 'lossy'>('all')
const freeOnly = ref(false)

const start = useMutation({
  mutationFn: () => api.post<{ ticket: number }>('/search', { query: q.value.trim() }),
  onSuccess: (d) => {
    ticket.value = d.ticket
    startedAt.value = Date.now()
    router.replace({ query: { q: q.value.trim(), t: d.ticket } })
  },
  onError: e => toast.error('Recherche impossible', { description: e.message }),
})

const { data: snap, error } = useQuery({
  queryKey: ['search', ticket],
  queryFn: () => api.get<SearchSnapshot>(`/search/${ticket.value}`),
  enabled: computed(() => ticket.value != null),
  // On rafraîchit pendant ~40 s : les pairs répondent au fil de l'eau
  refetchInterval: () => (Date.now() - startedAt.value < 40_000 ? 1500 : false),
})
const now = ref(Date.now())
useIntervalFn(() => (now.value = Date.now()), 1000)
const listening = computed(() => ticket.value != null && now.value - startedAt.value < 40_000)

const hidden = computed(() => (snap.value?.folders.length ?? 0) - folders.value.length)
const folders = computed(() => (snap.value?.folders ?? []).filter((f) => {
  if (freeOnly.value && !f.has_free_slots)
    return false
  if (quality.value === 'lossless')
    return f.formats.some(x => LOSSLESS.has(x))
  if (quality.value === 'lossy')
    return f.formats.length > 0 && f.formats.every(x => !LOSSLESS.has(x))
  return true
}))

const download = useMutation({
  mutationFn: (v: { username: string, files: string[] }) => api.post<{ ids: number[] }>('/downloads', v),
  onSuccess: (d, v) => toast.success(`${d.ids.length} fichier(s) en file`, {
    description: `Depuis ${v.username}, vers ${status.value?.paths.downloads ?? 'downloads'}/manual/${v.username}/`,
  }),
  onError: e => toast.error(e.message),
})
</script>

<template>
  <div class="flex flex-col">
    <PageHeader
      eyebrow="Réseau"
      title="Recherche manuelle"
      description="Interroge directement le réseau Soulseek. Les résultats sont groupés par dossier ; un téléchargement manuel n’est pas importé automatiquement dans la bibliothèque."
    />

    <form class="mb-5 flex flex-col gap-3 sm:flex-row" @submit.prevent="q.trim().length >= 2 && start.mutate()">
      <InputGroup class="flex-1">
        <InputGroupAddon>
          <SearchIcon />
        </InputGroupAddon>
        <InputGroupInput v-model="q" placeholder="artiste album, mots-clés… (-mot pour exclure)" autofocus />
        <InputGroupAddon v-if="listening" align="inline-end">
          <Spinner />
        </InputGroupAddon>
      </InputGroup>
      <Button type="submit" :disabled="start.isPending.value || q.trim().length < 2">
        Chercher
      </Button>
    </form>

    <Alert v-if="error" variant="destructive" class="mb-5">
      <AlertDescription>{{ error.message }}</AlertDescription>
    </Alert>

    <template v-if="snap">
      <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <p class="font-mono text-[12px] text-muted-foreground tnum">
          {{ snap.peer_count }} pairs · {{ snap.file_count }} fichiers · {{ snap.folders.length }} dossiers
          <span v-if="listening" class="text-primary"> · écoute des réponses…</span>
        </p>
        <div class="flex items-center gap-4 sm:ml-auto">
          <label class="flex items-center gap-2 text-[12.5px] text-muted-foreground">
            <Switch v-model="freeOnly" />
            Slot libre
          </label>
          <ToggleGroup v-model="quality" type="single" variant="outline" size="sm">
            <ToggleGroupItem value="all">
              Tout
            </ToggleGroupItem>
            <ToggleGroupItem value="lossless">
              Lossless
            </ToggleGroupItem>
            <ToggleGroupItem value="lossy">
              Compressé
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>

      <div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div class="flex min-w-0 flex-col gap-2">
        <p v-if="hidden" class="text-[12px] text-faint">
          {{ hidden }} dossier(s) masqué(s) par les filtres.
        </p>
        <FolderResult
          v-for="f in folders"
          :key="`${f.username}|${f.directory}`"
          :username="f.username"
          :directory="f.directory"
          :files="f.files"
          :formats="f.formats"
          :has-free-slots="f.has_free_slots"
          :avg-speed="f.avg_speed"
          :queue-size="f.queue_size"
          show-peer
          @download="(files) => download.mutate({ username: f.username, files })"
        />
        <p v-if="!folders.length && !listening" class="py-10 text-center text-[12.5px] text-faint">
          Aucun dossier ne correspond aux filtres.
        </p>
      </div>

      <!-- Ce qui se passe vraiment : chaque pair qui répond, dans l'ordre d'arrivée -->
      <aside class="flex flex-col gap-2 rounded-lg border bg-card p-4 xl:sticky xl:top-20">
        <div class="flex items-baseline justify-between">
          <h2 class="text-[13px] font-semibold">
            Réponses en direct
          </h2>
          <RouterLink :to="{ name: 'logs' }" class="text-[11.5px] text-faint hover:text-primary">
            Logs →
          </RouterLink>
        </div>
        <p class="text-[11.5px] leading-relaxed text-muted-foreground">
          Le serveur relaie ta requête ; chaque pair qui a des fichiers correspondants te répond directement.
          <template v-if="listening">
            Écoute depuis {{ Math.round((now - startedAt) / 1000) }} s.
          </template>
        </p>
        <ol class="scrollbar-thin flex max-h-[60svh] flex-col overflow-y-auto font-mono text-[11px]">
          <li
            v-for="(r, i) in snap.responses ?? []"
            :key="`${r.username}-${i}`"
            class="grid grid-cols-[3rem_minmax(0,1fr)_auto] items-baseline gap-2 border-b border-border/50 py-1 last:border-b-0"
          >
            <span class="text-faint tnum">+{{ r.at.toFixed(1) }}s</span>
            <span class="truncate text-foreground/90" :title="r.username">{{ r.username }}</span>
            <span class="text-right text-muted-foreground tnum">
              {{ r.files }} f · {{ r.folders }} d<span :class="r.free_slot ? 'text-success' : 'text-faint'"> ●</span>
            </span>
          </li>
          <li v-if="!(snap.responses ?? []).length" class="py-4 text-center font-sans text-faint">
            {{ listening ? 'En attente des premières réponses…' : 'Aucune réponse.' }}
          </li>
        </ol>
        <p class="text-[10.5px] text-faint">
          f = fichiers, d = dossiers, <span class="text-success">●</span> slot libre
        </p>
      </aside>
      </div>
    </template>

    <Empty v-else-if="!ticket" class="rounded-lg border border-dashed py-16">
      <EmptyHeader>
        <EmptyTitle class="text-[14px]">
          Cherche ce que tu veux
        </EmptyTitle>
        <EmptyDescription class="text-[12.5px]">
          Pour suivre un artiste et laisser Soulsick ranger proprement, passe plutôt par « Artistes ».
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  </div>
</template>

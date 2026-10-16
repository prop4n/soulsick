<script setup lang="ts">
import type { BrowseDirectory } from '@/lib/types'
import { FolderTreeIcon, LockIcon, SearchIcon } from '@lucide/vue'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import FolderResult from '@/components/FolderResult.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/lib/api'
import { bytes } from '@/lib/format'
import { isAudioName } from '@/lib/files'

const route = useRoute()
const router = useRouter()
const username = computed(() => (route.params.username as string) || '')
const input = ref(username.value)
const filter = ref('')

const { data, isFetching, error } = useQuery({
  queryKey: ['browse', username],
  queryFn: () => api.get<{ directories: BrowseDirectory[], locked: BrowseDirectory[] }>(`/users/${encodeURIComponent(username.value)}/browse`),
  enabled: computed(() => !!username.value),
  staleTime: 5 * 60_000,
  retry: false,
})

const dirs = computed(() => {
  const needle = filter.value.trim().toLowerCase()
  return (data.value?.directories ?? [])
    .filter(d => d.files.length && (!needle || d.path.toLowerCase().includes(needle)))
    .map(d => ({ ...d, files: d.files.map(f => ({ ...f, format: isAudioName(f.name) ? f.format : null })) }))
})
const totals = computed(() => {
  const all = data.value?.directories ?? []
  return { dirs: all.length, files: all.reduce((n, d) => n + d.files.length, 0), size: all.reduce((n, d) => n + d.files.reduce((s, f) => s + (f.size ?? 0), 0), 0) }
})

const download = useMutation({
  mutationFn: (files: string[]) => api.post<{ ids: number[] }>('/downloads', { username: username.value, files }),
  onSuccess: d => toast.success(`${d.ids.length} fichier(s) en file`),
  onError: e => toast.error(e.message),
})

function go() {
  if (input.value.trim())
    router.push({ name: 'browse', params: { username: input.value.trim() } })
}
</script>

<template>
  <div class="flex flex-col">
    <PageHeader
      eyebrow="Réseau"
      :title="username ? `Partages de ${username}` : 'Parcourir un pair'"
      description="Liste complète de ce qu’un utilisateur partage. Tu peux prendre un dossier entier ou quelques fichiers."
    />

    <form class="mb-5 flex gap-2" @submit.prevent="go">
      <InputGroup class="sm:max-w-sm">
        <InputGroupAddon>
          <FolderTreeIcon />
        </InputGroupAddon>
        <InputGroupInput v-model="input" placeholder="Nom d’utilisateur Soulseek" class="font-mono" />
      </InputGroup>
      <Button type="submit" variant="secondary">
        Parcourir
      </Button>
    </form>

    <div v-if="isFetching" class="flex flex-col gap-2">
      <p class="text-[12.5px] text-muted-foreground">
        Demande de la liste des partages à {{ username }}… (jusqu’à 90 s)
      </p>
      <Skeleton v-for="i in 6" :key="i" class="h-16 w-full" />
    </div>

    <Alert v-else-if="error" variant="destructive">
      <AlertTitle>Impossible de parcourir {{ username }}</AlertTitle>
      <AlertDescription>{{ error.message }}</AlertDescription>
    </Alert>

    <template v-else-if="data">
      <div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <p class="font-mono text-[12px] text-muted-foreground tnum">
          {{ totals.dirs }} dossiers · {{ totals.files }} fichiers · {{ bytes(totals.size) }}
          <span v-if="data.locked.length" class="text-faint"> · {{ data.locked.length }} dossiers verrouillés</span>
        </p>
        <InputGroup class="sm:ml-auto sm:max-w-xs">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput v-model="filter" placeholder="Filtrer les dossiers…" />
        </InputGroup>
      </div>
      <div class="flex flex-col gap-2">
        <FolderResult
          v-for="d in dirs.slice(0, 200)"
          :key="d.path"
          :username="username"
          :directory="d.path"
          :files="d.files"
          @download="(files) => download.mutate(files)"
        />
        <p v-if="dirs.length > 200" class="py-4 text-center text-[12px] text-faint">
          {{ dirs.length - 200 }} dossiers de plus — affine le filtre.
        </p>
      </div>
      <div v-if="data.locked.length" class="mt-6 flex items-center gap-2 text-[12px] text-faint">
        <LockIcon class="size-3.5" />
        Dossiers verrouillés (réservés aux amis de {{ username }}) : {{ data.locked.map(d => d.path.split('\\').pop()).slice(0, 8).join(', ') }}…
      </div>
    </template>

    <Empty v-else class="rounded-lg border border-dashed py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FolderTreeIcon />
        </EmptyMedia>
        <EmptyTitle class="text-[14px]">
          Choisis un pair
        </EmptyTitle>
        <EmptyDescription class="text-[12.5px]">
          Clique sur un nom d’utilisateur n’importe où dans Soulsick, ou tape-le ci-dessus.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  </div>
</template>

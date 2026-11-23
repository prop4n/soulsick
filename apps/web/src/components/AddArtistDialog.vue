<script setup lang="ts">
import type { MBArtist } from '@/lib/types'
import { CheckIcon, SearchIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { refDebounced } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'

const open = defineModel<boolean>('open', { default: false })
// Artists already chosen (Discover): only to confirm. Several at once are added in the background.
const props = defineProps<{ presets?: { mbid: string, name: string }[] }>()
const emit = defineEmits<{ done: [] }>()
const { t } = useI18n()
const router = useRouter()
const qc = useQueryClient()

const q = ref('')
const debounced = refDebounced(q, 350)
const many = ref<{ mbid: string, name: string }[]>([])

const { data: results, isFetching } = useQuery({
  queryKey: ['mb-artists', debounced],
  queryFn: () => api.get<MBArtist[]>(`/musicbrainz/artists?q=${encodeURIComponent(debounced.value)}`),
  enabled: computed(() => debounced.value.trim().length >= 2),
  staleTime: 60_000,
})

watch(open, (o) => {
  if (o && props.presets?.length)
    many.value = [...props.presets]
  if (!o) {
    setTimeout(() => {
      q.value = ''
      many.value = []
    }, 200)
  }
})

/** Following reads its discography on MusicBrainz: a few seconds, then its page opens */
const following = ref<string | null>(null)
const followOne = useMutation({
  mutationFn: async (r: MBArtist) => {
    following.value = r.mbid
    if (r.artist_id) {
      await api.post(`/artists/${r.artist_id}/follow`)
      return { id: r.artist_id, name: r.name }
    }
    return api.post<{ id: number, name: string }>('/artists', { mbid: r.mbid })
  },
  onSuccess: (a) => {
    toast.success(t('addArtist.added', { name: a.name }), { description: t('addArtist.addedHint') })
    qc.invalidateQueries({ queryKey: ['artists'] })
    open.value = false
    router.push({ name: 'artist', params: { id: a.id } })
  },
  onError: e => toast.error(t('addArtist.failed'), { description: e.message }),
  onSettled: () => (following.value = null),
})
function pick(r: MBArtist) {
  if (r.followed && r.artist_id) {
    open.value = false
    router.push({ name: 'artist', params: { id: r.artist_id } })
    return
  }
  followOne.mutate(r)
}

const followMany = useMutation({
  mutationFn: () => api.post<{ queued: number }>('/artists/bulk', { mbids: many.value.map(a => a.mbid) }),
  onSuccess: (r) => {
    toast.success(t('addArtist.addingMany', { n: r.queued }, r.queued), { description: t('addArtist.addingManyHint') })
    open.value = false
    emit('done')
  },
  onError: e => toast.error(t('addArtist.failed'), { description: e.message }),
})
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="gap-0 overflow-hidden p-0 sm:max-w-[560px]">
      <DialogHeader class="border-b px-6 pt-5 pb-4">
        <DialogTitle class="text-[16px]">
          {{ many.length ? t('addArtist.followMany', { n: many.length }, many.length) : t('common.followArtist') }}
        </DialogTitle>
        <DialogDescription class="text-[13px]">
          {{ many.length ? t('addArtist.howManyHint') : t('addArtist.searchHint') }}
        </DialogDescription>
      </DialogHeader>

      <!-- Artists chosen elsewhere: confirm -->
      <template v-if="many.length">
        <p class="line-clamp-4 px-6 py-5 text-[13px] text-foreground">
          {{ many.map(a => a.name).join(', ') }}
        </p>
        <DialogFooter class="border-t bg-well/50 px-6 py-3 sm:justify-between">
          <Button type="button" variant="ghost" size="sm" @click="open = false">
            {{ t('common.cancel') }}
          </Button>
          <Button size="sm" :disabled="followMany.isPending.value" @click="followMany.mutate()">
            <Spinner v-if="followMany.isPending.value" data-icon="inline-start" />
            {{ t('addArtist.followMany', { n: many.length }, many.length) }}
          </Button>
        </DialogFooter>
      </template>

      <!-- Search, then a click follows -->
      <div v-else class="flex flex-col gap-3 p-4">
        <InputGroup>
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput v-model="q" :placeholder="t('addArtist.placeholder')" autofocus />
          <InputGroupAddon v-if="isFetching" align="inline-end">
            <Spinner />
          </InputGroupAddon>
        </InputGroup>
        <div class="scrollbar-thin -mx-1 flex max-h-[380px] min-h-[120px] flex-col overflow-y-auto px-1">
          <template v-if="isFetching && !results">
            <Skeleton v-for="i in 4" :key="i" class="mb-2 h-12 w-full" />
          </template>
          <button
            v-for="r in results ?? []"
            :key="r.mbid"
            type="button"
            :disabled="followOne.isPending.value"
            class="flex items-center gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-accent disabled:cursor-default"
            @click="pick(r)"
          >
            <div class="flex min-w-0 flex-1 flex-col gap-1">
              <div class="flex items-baseline gap-2">
                <span class="truncate text-[14px] font-medium">{{ r.name }}</span>
                <span v-if="r.disambiguation" class="truncate text-[12px] text-muted-foreground">{{ r.disambiguation }}</span>
              </div>
              <div class="flex items-center gap-2 text-[12px] text-faint">
                <span v-if="r.type">{{ r.type }}</span>
                <span v-if="r.country" class="font-mono">{{ r.country }}</span>
                <span v-if="r.begin" class="font-mono tnum">{{ r.begin.slice(0, 4) }}</span>
                <span v-if="r.tags.length" class="truncate">· {{ r.tags.join(', ') }}</span>
              </div>
            </div>
            <Spinner v-if="following === r.mbid" class="size-4 text-muted-foreground" />
            <span v-else-if="r.followed" class="inline-flex items-center gap-1 text-[12px] text-success">
              <CheckIcon class="size-3" />{{ t('addArtist.followed') }}
            </span>
            <span v-else class="text-[12px] text-muted-foreground">{{ t('artist.follow') }}</span>
          </button>
          <p v-if="results && !results.length" class="py-8 text-center text-[13px] text-faint">
            {{ t('addArtist.noResult') }}
          </p>
          <p v-if="!results && !isFetching" class="py-8 text-center text-[13px] text-faint">
            {{ t('addArtist.typeMore') }}
          </p>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

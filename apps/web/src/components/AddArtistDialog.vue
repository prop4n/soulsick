<script setup lang="ts">
import type { ArtistMode, MBArtist } from '@/lib/types'
import { ArrowLeftIcon, CheckIcon, SearchIcon } from '@lucide/vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { refDebounced } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useProfiles } from '@/composables/queries'
import { api } from '@/lib/api'
import { RELEASE_TYPES, releaseTypeLabel, SECONDARY_TYPES } from '@/lib/status'
import { cn } from '@/lib/utils'

const open = defineModel<boolean>('open', { default: false })
// Artist already chosen (Discover, similar artists): straight to "how to follow it"
const props = defineProps<{ preset?: { mbid: string, name: string } | null }>()
const { t } = useI18n()
const router = useRouter()
const qc = useQueryClient()

const q = ref('')
const debounced = refDebounced(q, 350)
const picked = ref<MBArtist | null>(null)

const mode = ref<ArtistMode>('validation')
const profileId = ref<string>('')
const primary = ref<string[]>(['album', 'ep'])
const secondary = ref<string[]>([])
const monitor = ref<'all' | 'future' | 'none'>('none')

const { data: profiles } = useProfiles()
watch(profiles, (p) => {
  if (p?.length && !profileId.value)
    profileId.value = String(p[0]!.id)
}, { immediate: true })

const { data: results, isFetching } = useQuery({
  queryKey: ['mb-artists', debounced],
  queryFn: () => api.get<MBArtist[]>(`/musicbrainz/artists?q=${encodeURIComponent(debounced.value)}`),
  enabled: computed(() => debounced.value.trim().length >= 2),
  staleTime: 60_000,
})

watch(open, (o) => {
  if (o && props.preset) {
    picked.value = {
      mbid: props.preset.mbid,
      name: props.preset.name,
      sort_name: props.preset.name,
      disambiguation: '',
      country: null,
      type: null,
      score: 100,
      begin: null,
      tags: [],
      in_library: false,
    }
  }
  if (!o) {
    setTimeout(() => {
      q.value = ''
      picked.value = null
    }, 200)
  }
})

const add = useMutation({
  mutationFn: () => api.post<{ id: number, name: string }>('/artists', {
    mbid: picked.value!.mbid,
    mode: mode.value,
    quality_profile_id: profileId.value ? Number(profileId.value) : null,
    primary_types: primary.value,
    secondary_types: secondary.value,
    monitor: monitor.value,
  }),
  onSuccess: (a) => {
    toast.success(t('addArtist.added', { name: a.name }), { description: t('addArtist.addedHint') })
    qc.invalidateQueries({ queryKey: ['artists'] })
    open.value = false
    router.push({ name: 'artist', params: { id: a.id } })
  },
  onError: e => toast.error(t('addArtist.failed'), { description: e.message }),
})
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="gap-0 overflow-hidden p-0 sm:max-w-[560px]">
      <DialogHeader class="border-b px-6 pt-5 pb-4">
        <DialogTitle class="text-[16px]">
          {{ picked ? t('addArtist.follow', { name: picked.name }) : t('common.followArtist') }}
        </DialogTitle>
        <DialogDescription class="text-[12.5px]">
          {{ picked
            ? t('addArtist.howHint')
            : t('addArtist.searchHint') }}
        </DialogDescription>
      </DialogHeader>

      <!-- Step 1: pick the artist -->
      <div v-if="!picked" class="flex flex-col gap-3 p-4">
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
            <Skeleton v-for="i in 4" :key="i" class="mb-1.5 h-12 w-full" />
          </template>
          <button
            v-for="r in results ?? []"
            :key="r.mbid"
            type="button"
            :disabled="r.in_library"
            class="flex items-center gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-accent disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent"
            @click="picked = r"
          >
            <div class="flex min-w-0 flex-1 flex-col gap-0.5">
              <div class="flex items-baseline gap-2">
                <span class="truncate text-[13.5px] font-medium">{{ r.name }}</span>
                <span v-if="r.disambiguation" class="truncate text-[12px] text-muted-foreground">{{ r.disambiguation }}</span>
              </div>
              <div class="flex items-center gap-2 text-[11.5px] text-faint">
                <span v-if="r.type">{{ r.type }}</span>
                <span v-if="r.country" class="font-mono">{{ r.country }}</span>
                <span v-if="r.begin" class="font-mono tnum">{{ r.begin.slice(0, 4) }}</span>
                <span v-if="r.tags.length" class="truncate">· {{ r.tags.join(', ') }}</span>
              </div>
            </div>
            <Badge v-if="r.in_library" variant="success">
              <CheckIcon />{{ t('addArtist.followed') }}
            </Badge>
            <span v-else class="font-mono text-[10.5px] text-faint tnum">{{ r.score }}%</span>
          </button>
          <p v-if="results && !results.length" class="py-8 text-center text-[12.5px] text-faint">
            {{ t('addArtist.noResult') }}
          </p>
          <p v-if="!results && !isFetching" class="py-8 text-center text-[12.5px] text-faint">
            {{ t('addArtist.typeMore') }}
          </p>
        </div>
      </div>

      <!-- Step 2: how to follow -->
      <form v-else class="flex flex-col gap-6 px-6 py-5" @submit.prevent="add.mutate()">
        <FieldGroup>
          <FieldSet>
            <FieldLegend variant="label">
              {{ t('addArtist.whenFound') }}
            </FieldLegend>
            <ToggleGroup v-model="mode" type="single" variant="outline" class="grid w-full grid-cols-2">
              <ToggleGroupItem value="validation" class="h-auto flex-col items-start gap-0.5 px-3 py-2.5 text-left">
                <span class="text-[13px] font-medium">{{ t('artists.mode.validation') }}</span>
                <span class="text-[11.5px] font-normal text-muted-foreground">{{ t('addArtist.validationHint') }}</span>
              </ToggleGroupItem>
              <ToggleGroupItem value="auto" class="h-auto flex-col items-start gap-0.5 px-3 py-2.5 text-left">
                <span class="text-[13px] font-medium">{{ t('artists.mode.auto') }}</span>
                <span class="text-[11.5px] font-normal text-muted-foreground">{{ t('addArtist.autoHint') }}</span>
              </ToggleGroupItem>
            </ToggleGroup>
          </FieldSet>

          <Field>
            <FieldLabel>{{ t('artist.profile') }}</FieldLabel>
            <Select v-model="profileId">
              <SelectTrigger class="w-full">
                <SelectValue :placeholder="t('addArtist.pickProfile')" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem v-for="p in profiles ?? []" :key="p.id" :value="String(p.id)">
                    {{ p.name }}
                  </SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
            <FieldDescription>{{ t('addArtist.profileHint') }}</FieldDescription>
          </Field>

          <FieldSet>
            <FieldLegend variant="label">
              {{ t('artist.releaseTypes') }}
            </FieldLegend>
            <ToggleGroup v-model="primary" type="multiple" variant="outline" size="sm" class="flex-wrap justify-start">
              <ToggleGroupItem v-for="key in RELEASE_TYPES" :key="key" :value="key">
                {{ releaseTypeLabel(key) }}
              </ToggleGroupItem>
            </ToggleGroup>
            <FieldDescription>{{ t('addArtist.secondaryHint') }}</FieldDescription>
            <ToggleGroup v-model="secondary" type="multiple" variant="outline" size="sm" class="flex-wrap justify-start">
              <ToggleGroupItem v-for="key in SECONDARY_TYPES" :key="key" :value="key">
                {{ releaseTypeLabel(key) }}
              </ToggleGroupItem>
            </ToggleGroup>
          </FieldSet>

          <FieldSet>
            <FieldLegend variant="label">
              {{ t('addArtist.existing') }}
            </FieldLegend>
            <ToggleGroup v-model="monitor" type="single" variant="outline" size="sm" class="flex-wrap justify-start">
              <ToggleGroupItem value="none">
                {{ t('addArtist.monitor.none') }}
              </ToggleGroupItem>
              <ToggleGroupItem value="future">
                {{ t('addArtist.monitor.future') }}
              </ToggleGroupItem>
              <ToggleGroupItem value="all">
                {{ t('addArtist.monitor.all') }}
              </ToggleGroupItem>
            </ToggleGroup>
            <FieldDescription>
              {{ monitor === 'all'
                ? t('addArtist.monitorAllHint')
                : t('addArtist.monitorHint') }}
            </FieldDescription>
          </FieldSet>
        </FieldGroup>

        <DialogFooter :class="cn('-mx-6 -mb-5 border-t bg-well/50 px-6 py-3.5 sm:justify-between')">
          <Button type="button" variant="ghost" size="sm" @click="picked = null">
            <ArrowLeftIcon data-icon="inline-start" />
            {{ t('addArtist.other') }}
          </Button>
          <Button type="submit" size="sm" :disabled="add.isPending.value || !primary.length">
            <Spinner v-if="add.isPending.value" data-icon="inline-start" />
            {{ t('addArtist.follow', { name: picked.name }) }}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>

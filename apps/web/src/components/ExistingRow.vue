<script setup lang="ts">
import type { ExistingGroup } from '@/lib/types'
import { ChevronDownIcon, FolderIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'
import { bytes, splitPath, year } from '@/lib/format'
import { cn } from '@/lib/utils'
import CoverArt from './CoverArt.vue'
import FormatTag from './FormatTag.vue'

/** A folder of existing music: what we guess, what MusicBrainz proposes, and the import. */
const props = defineProps<{ group: ExistingGroup }>()
const { t } = useI18n()
const qc = useQueryClient()

const g = computed(() => props.group)
const name = computed(() => splitPath(g.value.dir))
const proposals = computed(() => g.value.result?.proposals ?? [])
const pick = ref('0')
const follow = ref(false)
const artist = ref(g.value.result?.query?.artist ?? g.value.guess.artist)
const album = ref(g.value.result?.query?.album ?? g.value.guess.album)
const open = ref(false)
watch(() => g.value.result, () => (pick.value = '0'))
const p = computed(() => proposals.value[Number(pick.value)])

const identify = useMutation({
  mutationFn: () => api.post('/library/existing/identify', { dir: g.value.dir, artist: artist.value, album: album.value }),
  onSuccess: () => qc.invalidateQueries({ queryKey: ['existing'] }),
  onError: e => toast.error(e.message),
})
const apply = useMutation({
  mutationFn: () => api.post<{ moved: number, album_dir: string }>('/library/existing/apply', {
    dir: g.value.dir,
    release_group_mbid: p.value!.release_group_mbid,
    release_mbid: p.value!.release_mbid,
    follow: follow.value,
  }),
  onSuccess: (d) => {
    toast.success(t('import.row.shelved', { album: `${p.value?.artist_name} – ${p.value?.title}` }), { description: `${t('library.fileCount', d.moved)} → ${d.album_dir}` })
    for (const key of ['existing', 'status', 'albums', 'transfers'])
      qc.invalidateQueries({ queryKey: [key] })
  },
  onError: e => toast.error(t('import.row.failed'), { description: e.message }),
})
</script>

<template>
  <div class="flex flex-col gap-3 rounded-xl bg-card p-4">
    <div class="flex min-w-0 items-start gap-3">
      <FolderIcon class="mt-0.5 size-4 shrink-0 text-faint" :stroke-width="1.75" />
      <div class="flex min-w-0 flex-1 flex-col gap-0.5">
        <span class="truncate font-mono text-[12.5px]" :title="g.dir">{{ name.name }}</span>
        <span class="truncate font-mono text-[11px] text-faint" :title="g.dir">{{ name.dir }}</span>
      </div>
      <div class="flex shrink-0 items-center gap-2 text-[11.5px] text-muted-foreground">
        <FormatTag :format="g.format" />
        <span class="font-mono tnum">{{ t('library.fileCount', g.files) }} · {{ bytes(g.size) }}</span>
      </div>
    </div>

    <!-- Proposed match -->
    <div v-if="p" class="flex flex-col gap-3 rounded-lg bg-well/60 p-3 sm:flex-row sm:items-center">
      <CoverArt :mbid="p.release_group_mbid" class="size-14 shrink-0" :alt="p.title" />
      <div class="flex min-w-0 flex-1 flex-col gap-1">
        <div class="flex min-w-0 flex-wrap items-baseline gap-x-2">
          <span class="truncate text-[13.5px] font-medium">{{ p.artist_name }} – {{ p.title }}</span>
          <span class="font-mono text-[11px] text-faint tnum">{{ year(p.date) }}</span>
          <Badge :variant="p.safe ? 'success' : 'warning'">
            {{ Math.round((p.partial ? p.file_confidence ?? 0 : p.confidence) * 100) }} %
          </Badge>
          <Badge v-if="p.partial" variant="quiet">
            {{ t('import.row.partial', { n: p.matched, total: p.track_count }) }}
          </Badge>
        </div>
        <p class="truncate text-[12px] text-muted-foreground">
          {{ t('import.row.matched', { n: p.matched, total: p.track_count }) }} · {{ p.release_info || p.release_title }}
          <span v-if="p.missing_tracks.length && !p.partial" class="text-warning"> · {{ t('import.row.missing', { tracks: p.missing_tracks.slice(0, 3).join(', ') + (p.missing_tracks.length > 3 ? '…' : '') }) }}</span>
          <span v-if="p.unmatched_files.length" class="text-warning"> · {{ t('import.row.unmatched', p.unmatched_files.length) }}</span>
        </p>
        <p v-if="p.destination" class="truncate font-mono text-[11px] text-faint" :title="p.destination">
          → {{ p.destination }}
        </p>
      </div>
      <div class="flex shrink-0 flex-col gap-2 sm:items-end">
        <Select v-if="proposals.length > 1" v-model="pick">
          <SelectTrigger size="sm" class="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem v-for="(x, i) in proposals" :key="x.release_mbid" :value="String(i)">
                {{ x.artist_name }} – {{ x.title }} ({{ Math.round((x.partial ? x.file_confidence ?? 0 : x.confidence) * 100) }} %)
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Checkbox v-model="follow" />
            {{ t('import.row.follow') }}
          </label>
          <Button size="sm" :variant="p.safe ? 'default' : 'outline'" :disabled="apply.isPending.value" @click="apply.mutate()">
            <Spinner v-if="apply.isPending.value" data-icon="inline-start" />
            {{ t('import.row.apply') }}
          </Button>
        </div>
      </div>
    </div>
    <p v-else-if="g.result" class="text-[12.5px] text-warning">
      {{ g.result.error ?? t('import.row.noMatch', { query: `${g.result.query?.artist} – ${g.result.query?.album}` }) }}
      {{ t('import.row.fixQuery') }}
    </p>

    <!-- Query (guessed, editable) -->
    <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
      <Input v-model="artist" class="h-8 text-[12.5px] sm:w-56" :placeholder="t('import.row.artist')" />
      <Input v-model="album" class="h-8 text-[12.5px] sm:w-72" :placeholder="t('import.row.album')" />
      <Button size="sm" :variant="g.result ? 'ghost' : 'secondary'" :disabled="identify.isPending.value || !album" @click="identify.mutate()">
        <Spinner v-if="identify.isPending.value" data-icon="inline-start" />
        {{ g.result ? t('import.row.retry') : t('import.row.identify') }}
      </Button>
      <Collapsible v-if="p" v-model:open="open" class="sm:ml-auto">
        <CollapsibleTrigger as-child>
          <Button variant="ghost" size="sm" class="text-muted-foreground">
            {{ t('import.row.mapping') }}
            <ChevronDownIcon data-icon="inline-end" :class="cn('transition-transform', open && 'rotate-180')" />
          </Button>
        </CollapsibleTrigger>
      </Collapsible>
    </div>
    <ul v-if="p && open" class="flex flex-col divide-y divide-border/60 rounded-lg bg-well/60 px-3 py-1 font-mono text-[11.5px]">
      <li v-for="m in p.mapping" :key="m.file" class="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] gap-3 py-1">
        <span class="truncate text-muted-foreground" :title="m.file">{{ m.name }}</span>
        <span class="text-faint">→</span>
        <span :class="cn('truncate', m.track ? 'text-foreground/90' : 'text-warning')">{{ m.track ?? t('import.row.noTrack') }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import type { JournalEvent } from '@/lib/types'
import { SearchIcon } from '@lucide/vue'
import { refDebounced } from '@vueuse/core'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import EventFeed from '@/components/EventFeed.vue'
import { Button } from '@/components/ui/button'
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useEvents } from '@/composables/queries'
import { api } from '@/lib/api'
import { eventText } from '@/lib/serverText'
import { EVENT_FAMILIES, eventFamilyLabel } from '@/lib/status'
import { useLive } from '@/stores/live'

/** The journal: every decision Soulsick made, newest first, append-only. */
const { t } = useI18n()
const live = useLive()
const family = ref('all')
const level = ref('all')
const q = ref('')
const dq = refDebounced(q, 300)

const params = computed(() => ({
  limit: 150,
  kind: family.value === 'all' ? undefined : family.value,
  level: level.value === 'all' ? undefined : level.value,
  q: dq.value || undefined,
}))
const { data, isPending } = useEvents(params)
const older = ref<JournalEvent[]>([])
const exhausted = ref(false)
watch(params, () => {
  older.value = []
  exhausted.value = false
})

function matches(e: JournalEvent) {
  return (family.value === 'all' || e.kind.startsWith(family.value))
    && (level.value === 'all' || e.level === level.value)
    && (!dq.value || eventText(e).toLowerCase().includes(dq.value.toLowerCase()))
}

const events = computed(() => {
  const base = data.value ?? []
  const seen = new Set(base.map(e => e.id))
  const fresh = live.events.filter(e => !seen.has(e.id) && e.id > (base[0]?.id ?? 0) && matches(e))
  return [...fresh, ...base, ...older.value]
})

const loadingMore = ref(false)
async function more() {
  const last = events.value.at(-1)
  if (!last)
    return
  loadingMore.value = true
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries({ ...params.value, before: last.id })) {
    if (v !== undefined)
      p.set(k, String(v))
  }
  const page = await api.get<JournalEvent[]>(`/events?${p}`)
  older.value = [...older.value, ...page]
  exhausted.value = page.length < 150
  loadingMore.value = false
}
</script>

<template>
  <div class="flex flex-col">
    <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
      <InputGroup class="lg:max-w-xs">
        <InputGroupAddon>
          <SearchIcon />
        </InputGroupAddon>
        <InputGroupInput v-model="q" :placeholder="t('activity.journal.searchPlaceholder')" />
      </InputGroup>
      <Select v-model="family">
        <SelectTrigger class="w-full lg:w-48">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="all">
              {{ t('activity.journal.allFamilies') }}
            </SelectItem>
            <SelectItem v-for="f in EVENT_FAMILIES" :key="f" :value="f">
              {{ eventFamilyLabel(f) }}
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <ToggleGroup v-model="level" type="single" variant="outline" size="sm" class="justify-start">
        <ToggleGroupItem value="all">
          {{ t('common.all') }}
        </ToggleGroupItem>
        <ToggleGroupItem value="warning">
          {{ t('common.warnings') }}
        </ToggleGroupItem>
        <ToggleGroupItem value="error">
          {{ t('common.errors') }}
        </ToggleGroupItem>
      </ToggleGroup>
    </div>

    <div v-if="isPending" class="flex flex-col gap-2">
      <Skeleton v-for="i in 10" :key="i" class="h-8 w-full" />
    </div>
    <template v-else>
      <EventFeed :events="events" />
      <p v-if="!events.length" class="py-12 text-center text-[12.5px] text-faint">
        {{ t('activity.journal.empty') }}
      </p>
      <div v-else-if="!exhausted && events.length >= 150" class="flex justify-center py-6">
        <Button variant="outline" size="sm" :disabled="loadingMore" @click="more">
          {{ t('activity.journal.older') }}
        </Button>
      </div>
    </template>
  </div>
</template>

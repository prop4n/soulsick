<script setup lang="ts">
import type { SimilarArtist } from '@/lib/types'
import { PlusIcon } from '@lucide/vue'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import AddArtistDialog from '@/components/AddArtistDialog.vue'
import { api } from '@/lib/api'

const props = defineProps<{ artistId: number }>()
const { t } = useI18n()

const { data } = useQuery({
  queryKey: ['similar', computed(() => props.artistId)],
  queryFn: () => api.get<SimilarArtist[]>(`/artists/${props.artistId}/similar`),
  staleTime: 5 * 60_000,
})
const list = computed(() => (data.value ?? []).slice(0, 12))

const following = ref<{ mbid: string, name: string } | null>(null)
const addOpen = ref(false)
function follow(a: SimilarArtist) {
  following.value = { mbid: a.mbid, name: a.name }
  addOpen.value = true
}
</script>

<template>
  <section class="flex flex-col">
    <h2 class="text-[14px] font-semibold">
      {{ t('discover.similar') }}
    </h2>
    <p v-if="!list.length" class="pt-3 text-[12.5px] text-faint">
      {{ t('discover.similarPending') }}
    </p>
    <ul v-else class="flex flex-col pt-2">
      <li
        v-for="a in list"
        :key="a.mbid"
        class="group flex items-center gap-2 border-b border-white/[0.04] py-1.5 last:border-b-0"
      >
        <RouterLink
          v-if="a.followed_id"
          :to="{ name: 'artist', params: { id: a.followed_id } }"
          class="min-w-0 flex-1 truncate text-[13px] hover:text-primary"
        >
          {{ a.name }}
        </RouterLink>
        <span v-else class="min-w-0 flex-1 truncate text-[13px]" :title="a.comment || undefined">{{ a.name }}</span>
        <span v-if="a.followed_id" class="text-[11px] text-faint">{{ t('discover.followed') }}</span>
        <button
          v-else
          type="button"
          class="flex items-center gap-1 rounded px-1.5 text-[11.5px] text-muted-foreground opacity-70 hover:bg-white/5 hover:text-foreground group-hover:opacity-100"
          @click="follow(a)"
        >
          <PlusIcon class="size-3" />
          {{ t('discover.follow') }}
        </button>
      </li>
    </ul>
    <AddArtistDialog v-model:open="addOpen" :presets="following ? [following] : []" />
  </section>
</template>

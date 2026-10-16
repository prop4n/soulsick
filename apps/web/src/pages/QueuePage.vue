<script setup lang="ts">
import { computed, ref } from 'vue'
import AlbumRow from '@/components/AlbumRow.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAlbums } from '@/composables/queries'

const tabs = {
  approval: { status: 'pending_approval', label: 'À valider', empty: 'Aucune proposition en attente.', hint: 'Albums trouvés pour des artistes en mode validation : ouvre-les pour comparer les candidats.' },
  review: { status: 'needs_review', label: 'À vérifier', empty: 'Aucun import à vérifier.', hint: 'Fichiers reçus mais association incertaine : rien n’a été rangé, à toi de confirmer.' },
  active: { status: 'searching,downloading,importing', label: 'En cours', empty: 'Rien en cours.', hint: 'Recherches, téléchargements et imports en ce moment.' },
  wanted: { status: 'wanted,failed', label: 'Recherchés', empty: 'Aucun album recherché.', hint: 'Albums suivis absents de la bibliothèque, avec la raison du dernier essai.' },
} as const

type TabKey = keyof typeof tabs
const tab = ref<TabKey>('approval')
const status = computed(() => tabs[tab.value].status)
const { data, isPending } = useAlbums(status)
const counts = {
  approval: useAlbums('pending_approval').data,
  review: useAlbums('needs_review').data,
}
</script>

<template>
  <div class="flex flex-col">
    <PageHeader
      eyebrow="Bibliothèque"
      title="File"
      description="Tout ce qui attend une décision ou une étape, album par album."
    />

    <Tabs v-model="tab" class="mb-5">
      <TabsList>
        <TabsTrigger v-for="(t, key) in tabs" :key="key" :value="key">
          {{ t.label }}
          <span
            v-if="key in counts && counts[key as 'approval' | 'review'].value?.length"
            class="ml-1 rounded-[3px] bg-warning/15 px-1 font-mono text-[10.5px] text-warning tnum"
          >{{ counts[key as 'approval' | 'review'].value?.length }}</span>
        </TabsTrigger>
      </TabsList>
    </Tabs>
    <p class="mb-4 text-[12.5px] text-muted-foreground">
      {{ tabs[tab].hint }}
    </p>

    <div v-if="isPending" class="flex flex-col gap-2">
      <Skeleton v-for="i in 5" :key="i" class="h-14 w-full" />
    </div>
    <div v-else-if="data?.length" class="flex flex-col rounded-lg border bg-card p-1.5">
      <AlbumRow v-for="a in data" :key="a.id" :album="a" show-artist />
    </div>
    <Empty v-else class="rounded-lg border border-dashed py-14">
      <EmptyHeader>
        <EmptyTitle class="text-[14px]">
          {{ tabs[tab].empty }}
        </EmptyTitle>
        <EmptyDescription class="text-[12.5px]">
          {{ tabs[tab].hint }}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  </div>
</template>

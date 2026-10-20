<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import JournalPanel from '@/components/JournalPanel.vue'
import LogsPanel from '@/components/LogsPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useLive } from '@/stores/live'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const live = useLive()

const tab = ref(route.query.tab === 'logs' ? 'logs' : 'journal')
watch(tab, v => router.replace({ query: v === 'journal' ? {} : { tab: v } }))

onMounted(() => (live.unseenProblems = 0))
onUnmounted(() => (live.unseenProblems = 0))
</script>

<template>
  <div class="flex flex-col">
    <PageHeader :title="t('activity.title')" :description="t(`activity.${tab}.description`)" />
    <Tabs v-model="tab" class="gap-5">
      <TabsList>
        <TabsTrigger value="journal">
          {{ t('activity.journal.tab') }}
        </TabsTrigger>
        <TabsTrigger value="logs">
          {{ t('activity.logs.tab') }}
        </TabsTrigger>
      </TabsList>
      <TabsContent value="journal">
        <JournalPanel />
      </TabsContent>
      <TabsContent value="logs">
        <LogsPanel />
      </TabsContent>
    </Tabs>
  </div>
</template>

<script setup lang="ts">
import type { StorageDisk } from '@/lib/types'
import { HardDriveIcon, RefreshCwIcon, TriangleAlertIcon } from '@lucide/vue'
import { useQueryClient } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useStatus, useStorage } from '@/composables/queries'
import { api } from '@/lib/api'
import { bytes } from '@/lib/format'
import { serverText } from '@/lib/serverText'
import { cn } from '@/lib/utils'

/**
 * Disks used by Soulsick: free space, and which of its folders live there.
 * Folders on the same disk are grouped (in Docker, several volumes often share one disk).
 */
const { t } = useI18n()
const qc = useQueryClient()
const { data, isPending } = useStorage()
const { data: status } = useStatus()

const refreshing = ref(false)
async function refresh() {
  refreshing.value = true
  try {
    qc.setQueryData(['storage'], await api.get<{ disks: StorageDisk[] }>('/storage?refresh=true'))
  }
  finally {
    refreshing.value = false
  }
}

const pct = (n: number, d: StorageDisk) => (d.total ? (n / d.total) * 100 : 0)
</script>

<template>
  <section class="flex flex-col gap-3">
    <div class="flex items-center justify-between gap-3">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-[14px] font-semibold">
          {{ t('storage.title') }}
        </h3>
        <p class="text-[12px] text-muted-foreground">
          {{ t('storage.hint') }}
        </p>
      </div>
      <Button variant="ghost" size="sm" class="text-muted-foreground" :disabled="refreshing" @click="refresh">
        <RefreshCwIcon data-icon="inline-start" :class="cn(refreshing && 'animate-spin')" />
        {{ t('storage.refresh') }}
      </Button>
    </div>

    <div v-if="status?.library_guard.warnings.length" class="flex flex-col gap-1.5 rounded-xl bg-warning/10 p-4 ring-1 ring-inset ring-warning/30">
      <p class="flex items-center gap-2 text-[13px] font-semibold text-warning">
        <TriangleAlertIcon class="size-4" />
        {{ t('libraryGuard.warnings') }}
      </p>
      <p v-for="(w, i) in status.library_guard.warnings" :key="i" class="text-[12.5px] text-foreground/85">
        {{ serverText(w, status.library_guard.warnings_t[i]) }}
      </p>
    </div>

    <Skeleton v-if="isPending" class="h-36 w-full" />
    <div
      v-for="d in data?.disks ?? []"
      :key="d.id"
      :class="cn('flex flex-col gap-3 rounded-xl bg-card p-4 ring-1 ring-inset',
                 d.level === 'critical' ? 'ring-destructive/40' : d.level === 'low' ? 'ring-warning/40' : 'ring-transparent')"
    >
      <template v-if="d.id !== -1">
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <HardDriveIcon class="size-4 shrink-0 self-center text-faint" :stroke-width="1.75" />
          <span class="font-mono text-[20px] leading-none font-medium tnum">{{ bytes(d.free) }}</span>
          <span class="text-[12.5px] text-muted-foreground">{{ t('storage.freeOf', { total: bytes(d.total) }) }}</span>
          <Badge v-if="d.level !== 'ok'" :variant="d.level === 'critical' ? 'danger' : 'warning'" class="self-center">
            {{ t(`storage.level.${d.level}`) }}
          </Badge>
          <span class="ml-auto font-mono text-[11px] text-faint" :title="t('storage.mount')">{{ d.mount }}</span>
        </div>
        <!-- Soulsick | other files | free -->
        <div class="flex h-2 overflow-hidden rounded-full bg-border">
          <div class="h-full bg-primary" :style="{ width: d.soulsick ? `max(3px, ${pct(d.soulsick, d)}%)` : 0 }" :title="t('storage.legend.soulsick')" />
          <div class="h-full bg-muted-foreground/40" :style="{ width: `${Math.max(0, pct(d.used - d.soulsick, d))}%` }" :title="t('storage.legend.other')" />
        </div>
        <div class="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground">
          <span class="flex items-center gap-1.5"><span class="size-2 rounded-full bg-primary" />{{ t('storage.legend.soulsick') }} <span class="font-mono tnum">{{ bytes(d.soulsick) }}</span></span>
          <span class="flex items-center gap-1.5"><span class="size-2 rounded-full bg-muted-foreground/40" />{{ t('storage.legend.other') }} <span class="font-mono tnum">{{ bytes(Math.max(0, d.used - d.soulsick)) }}</span></span>
          <span class="flex items-center gap-1.5"><span class="size-2 rounded-full bg-border ring-1 ring-border-strong" />{{ t('storage.legend.free') }} <span class="font-mono tnum">{{ bytes(d.free) }}</span></span>
        </div>
      </template>
      <ul class="flex flex-col divide-y divide-border/60">
        <li v-for="f in d.folders" :key="`${f.key}:${f.path}`" class="flex items-center gap-3 py-1.5 text-[12.5px]">
          <span class="w-28 shrink-0 text-muted-foreground">{{ t(`storage.folder.${f.key}`) }}</span>
          <span class="min-w-0 flex-1 truncate font-mono text-[12px]" :title="f.path">{{ f.path }}</span>
          <span v-if="f.missing" class="text-[11.5px] text-destructive">{{ t('storage.missing') }}</span>
          <span v-else class="font-mono text-[11.5px] text-faint tnum">{{ bytes(f.size) }}</span>
        </li>
      </ul>
    </div>
  </section>
</template>

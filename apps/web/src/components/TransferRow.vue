<script setup lang="ts">
import type { Transfer } from '@/lib/types'
import { RotateCcwIcon, XIcon } from '@lucide/vue'
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { bytes, splitPath, speed } from '@/lib/format'
import { TRANSFER_STATE } from '@/lib/status'
import { cn } from '@/lib/utils'
import { useLive } from '@/stores/live'

const props = withDefaults(defineProps<{ transfer: Transfer, actions?: boolean, busy?: boolean }>(), { actions: true, busy: false })
const emit = defineEmits<{ cancel: [id: number], retry: [id: number] }>()
const live = useLive()

/** On fusionne la ligne en base avec la progression temps réel reçue par WebSocket. */
const t = computed(() => ({ ...props.transfer, ...(live.transfers.get(props.transfer.id) ?? {}) }) as Transfer)
const pct = computed(() => (t.value.size ? Math.min(100, (t.value.bytes_transferred / t.value.size) * 100) : 0))
const name = computed(() => splitPath(t.value.remote_path).name)
const running = computed(() => ['queued', 'initializing', 'transferring', 'paused'].includes(t.value.state))
const st = computed(() => {
  // « En file » ne veut rien dire seul : a-t-on l'accord du pair, et où en est-on chez lui ?
  if (t.value.direction === 'download' && t.value.state === 'queued') {
    return t.value.remotely_queued
      ? { label: t.value.place_in_queue ? `Dans sa file · #${t.value.place_in_queue}` : 'Dans sa file', badge: 'signal' as const }
      : { label: 'Demande envoyée', badge: 'quiet' as const }
  }
  return TRANSFER_STATE[t.value.state]
})
</script>

<template>
  <div class="group grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 py-2.5">
    <div class="flex min-w-0 items-center gap-2">
      <span class="truncate text-[13px] text-foreground" :title="t.remote_path">{{ name }}</span>
    </div>
    <div class="flex items-center gap-2">
      <span class="font-mono text-[11px] text-muted-foreground tnum">
        <template v-if="t.state === 'transferring'">{{ speed(t.speed) }} · </template>
        {{ bytes(t.bytes_transferred) }}<span class="text-faint"> / {{ bytes(t.size) }}</span>
      </span>
      <Tooltip>
        <TooltipTrigger as-child>
          <span class="inline-flex"><Badge :variant="st.badge">{{ st.label }}</Badge></span>
        </TooltipTrigger>
        <TooltipContent class="max-w-64">
          <template v-if="t.state === 'queued' && t.direction === 'download'">
            {{ t.remotely_queued
              ? `${t.username} a accepté la demande : le fichier partira quand ton tour viendra dans sa file d’envoi. Position actualisée toutes les 90 s.`
              : `En attente de la réponse de ${t.username} (hors ligne, injoignable, ou pas encore répondu).` }}
          </template>
          <template v-else>
            {{ st.label }}
          </template>
        </TooltipContent>
      </Tooltip>
      <span v-if="(t.attempts ?? 1) > 1" class="font-mono text-[10.5px] text-faint tnum" title="Tentatives">essai {{ t.attempts }}</span>
      <template v-if="actions">
        <Tooltip v-if="running">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="icon-xs" class="text-faint hover:text-destructive" aria-label="Annuler" :disabled="busy" @click="emit('cancel', t.id)">
              <XIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Annuler ce transfert</TooltipContent>
        </Tooltip>
        <Tooltip v-else-if="t.direction === 'download' && t.state !== 'complete'">
          <TooltipTrigger as-child>
            <Button variant="ghost" size="xs" class="text-muted-foreground hover:text-primary" :disabled="busy" @click="emit('retry', t.id)">
              <RotateCcwIcon data-icon="inline-start" />
              Relancer
            </Button>
          </TooltipTrigger>
          <TooltipContent>Redemander ce fichier au même pair (sur la même ligne)</TooltipContent>
        </Tooltip>
        <span v-else class="size-6" />
      </template>
    </div>
    <div class="col-span-2 flex min-w-0 items-center gap-3">
      <div class="h-[3px] flex-1 overflow-hidden rounded-full bg-border">
        <div
          :class="cn('h-full rounded-full transition-[width] duration-500',
                     t.state === 'complete' ? 'bg-success' : t.state === 'failed' ? 'bg-destructive' : 'bg-primary')"
          :style="{ width: `${t.state === 'complete' ? 100 : pct}%` }"
        />
      </div>
    </div>
    <div class="col-span-2 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-[11.5px]">
      <span class="text-faint">{{ t.direction === 'download' ? 'depuis' : 'vers' }}</span>
      <RouterLink :to="{ name: 'browse', params: { username: t.username } }" class="font-mono text-muted-foreground hover:text-primary">
        {{ t.username }}
      </RouterLink>
      <template v-if="t.local_path">
        <span class="text-faint">{{ t.direction === 'download' ? '→' : 'fichier' }}</span>
        <span class="min-w-0 truncate font-mono text-faint" :title="t.local_path">{{ t.local_path }}</span>
      </template>
      <span v-if="t.error" class="text-destructive">{{ t.error }}</span>
    </div>
  </div>
</template>

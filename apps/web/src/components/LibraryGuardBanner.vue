<script setup lang="ts">
import type { LibraryGuard } from '@/lib/types'
import { FolderXIcon, RefreshCwIcon } from '@lucide/vue'
import { useQueryClient } from '@tanstack/vue-query'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { serverText } from '@/lib/serverText'
import { cn } from '@/lib/utils'

/**
 * The library folder is missing, not mounted from the host or suddenly empty:
 * imports wait and scans are skipped until it is back. Shown above every page.
 */
const props = defineProps<{ guard: LibraryGuard }>()
const { t } = useI18n()
const qc = useQueryClient()

const checking = ref(false)
async function check() {
  checking.value = true
  try {
    const st = await api.post<LibraryGuard>('/library/guard/check')
    if (st.ok)
      toast.success(t('libraryGuard.back'))
    else
      toast.error(t('libraryGuard.still'))
    qc.invalidateQueries({ queryKey: ['status'] })
  }
  catch (e) {
    toast.error((e as Error).message)
  }
  finally {
    checking.value = false
  }
}

const confirmOpen = ref(false)
async function confirmEmpty() {
  confirmOpen.value = false
  try {
    const r = await api.post<LibraryGuard & { removed: number }>('/library/guard/confirm-empty')
    toast.success(t('libraryGuard.forgotten', r.removed))
    qc.invalidateQueries()
  }
  catch (e) {
    toast.error((e as Error).message)
  }
}

const emptied = () => props.guard.problem_t?.key === 'library.guard.emptied'
</script>

<template>
  <div role="alert" class="mb-6 flex flex-col gap-3 rounded-xl bg-destructive/10 p-4 ring-1 ring-destructive/30 sm:flex-row sm:items-center">
    <FolderXIcon class="size-5 shrink-0 text-destructive" />
    <div class="flex min-w-0 flex-1 flex-col gap-0.5">
      <p class="text-[13.5px] font-semibold text-destructive">
        {{ t('libraryGuard.title') }}
      </p>
      <p class="text-[12.5px] text-foreground/85 first-letter:uppercase">
        {{ serverText(guard.problem, guard.problem_t) }}
      </p>
      <p class="text-[12px] text-muted-foreground">
        {{ t('libraryGuard.hint') }}
      </p>
    </div>
    <div class="flex shrink-0 flex-wrap gap-2">
      <Button v-if="emptied()" variant="ghost" size="sm" class="text-muted-foreground" @click="confirmOpen = true">
        {{ t('libraryGuard.reallyEmpty') }}
      </Button>
      <Button variant="outline" size="sm" :disabled="checking" @click="check">
        <RefreshCwIcon data-icon="inline-start" :class="cn(checking && 'animate-spin')" />
        {{ t('libraryGuard.check') }}
      </Button>
    </div>

    <AlertDialog v-model:open="confirmOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{{ t('libraryGuard.confirmTitle') }}</AlertDialogTitle>
          <AlertDialogDescription>
            {{ t('libraryGuard.confirmText', { path: guard.path }) }}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{{ t('common.cancel') }}</AlertDialogCancel>
          <AlertDialogAction class="bg-destructive text-white hover:bg-destructive/90" @click="confirmEmpty">
            {{ t('libraryGuard.confirmAction') }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>

import { useQueryClient } from '@tanstack/vue-query'
import { ref } from 'vue'
import { toast } from 'vue-sonner'
import { t } from '@/i18n'
import { api } from '@/lib/api'

export type TransferAction = 'cancel' | 'retry' | 'pause' | 'resume'

/** Transfer actions (one row or a group), with feedback and double-click guard. */
export function useTransferActions() {
  const qc = useQueryClient()
  const busy = ref(new Set<number>())

  async function run(ids: number[], kind: TransferAction, quiet = false) {
    busy.value = new Set([...busy.value, ...ids])
    let ok = 0
    try {
      for (const id of ids) {
        try {
          const r = await api.post<{ ok?: boolean }>(`/transfers/${id}/${kind}`)
          if (r.ok !== false)
            ok++
        }
        catch (e) {
          toast.error((e as Error).message)
        }
      }
      if (!quiet && ok)
        toast.success(ids.length > 1 ? t(`transfer.done.${kind}Many`, ok) : t(`transfer.done.${kind}`))
      qc.invalidateQueries({ queryKey: ['transfers'] })
      qc.invalidateQueries({ queryKey: ['album'] })
    }
    finally {
      const next = new Set(busy.value)
      ids.forEach(i => next.delete(i))
      busy.value = next
    }
  }

  /** One action on many transfers in a single request (cancelling a whole album source drops it cleanly). */
  async function batch(ids: number[], kind: TransferAction) {
    if (!ids.length)
      return 0
    busy.value = new Set([...busy.value, ...ids])
    try {
      const r = await api.post<{ done: number }>('/transfers/batch', { ids, action: kind })
      toast.success(r.done ? t(`transfer.done.${kind}Many`, r.done) : t('transfer.nothingDone'))
      return r.done
    }
    catch (e) {
      toast.error((e as Error).message)
      return 0
    }
    finally {
      qc.invalidateQueries({ queryKey: ['transfers'] })
      qc.invalidateQueries({ queryKey: ['album'] })
      const next = new Set(busy.value)
      ids.forEach(i => next.delete(i))
      busy.value = next
    }
  }

  return { busy, run, batch }
}

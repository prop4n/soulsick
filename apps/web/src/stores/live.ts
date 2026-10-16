import type { QueryClient } from '@tanstack/vue-query'
import type { EngineStatus, HunterState, JournalEvent, LogLine, Transfer } from '@/lib/types'
import { defineStore } from 'pinia'
import { reactive, ref, shallowRef } from 'vue'

type Msg
  = | { type: 'status', data: EngineStatus }
    | { type: 'hunter', data: HunterState }
    | { type: 'event', data: JournalEvent }
    | { type: 'transfer', data: Partial<Transfer> & { id: number } }
    | { type: 'album', data: { id: number, status: string, status_reason?: string | null } }
    | { type: 'logs', data: LogLine[] }

/** Flux temps réel : statut réseau, chasse en cours, journal, progression des transferts. */
export const useLive = defineStore('live', () => {
  const engine = ref<EngineStatus | null>(null)
  const hunter = ref<HunterState | null>(null)
  const events = shallowRef<JournalEvent[]>([])
  /** Logs techniques (page Console), 3000 dernières lignes */
  const logs = shallowRef<LogLine[]>([])
  const unseen = ref(0)
  const transfers = reactive(new Map<number, Partial<Transfer>>())
  const connected = ref(false)
  /** Historique court des vitesses pour le VU-mètre de la barre latérale */
  const speedHistory = ref<{ down: number, up: number }[]>([])

  let socket: WebSocket | null = null
  let retry = 0
  let client: QueryClient | null = null
  let invalidateTimer: ReturnType<typeof setTimeout> | null = null
  const pendingKeys = new Set<string>()

  function invalidate(...keys: string[]) {
    keys.forEach(k => pendingKeys.add(k))
    if (invalidateTimer)
      return
    // Regroupe les invalidations : un import produit des dizaines d'événements d'affilée
    invalidateTimer = setTimeout(() => {
      invalidateTimer = null
      for (const k of pendingKeys)
        client?.invalidateQueries({ queryKey: [k] })
      pendingKeys.clear()
    }, 400)
  }

  function handle(msg: Msg) {
    switch (msg.type) {
      case 'status':
        engine.value = msg.data
        speedHistory.value = [...speedHistory.value.slice(-59), { down: msg.data.download_speed, up: msg.data.upload_speed }]
        break
      case 'hunter':
        hunter.value = msg.data
        break
      case 'event':
        events.value = [msg.data, ...events.value].slice(0, 300)
        unseen.value++
        invalidate('events', 'status')
        if (msg.data.release_group_id)
          invalidate('album', 'albums', 'artist')
        if (msg.data.kind.startsWith('artist') || msg.data.kind.startsWith('musicbrainz'))
          invalidate('artists', 'artist')
        if (msg.data.kind.startsWith('share'))
          invalidate('shares')
        break
      case 'transfer': {
        const prev = transfers.get(msg.data.id) ?? {}
        transfers.set(msg.data.id, { ...prev, ...msg.data })
        if (msg.data.state && msg.data.state !== prev.state)
          invalidate('transfers', 'album')
        break
      }
      case 'album':
        invalidate('album', 'albums', 'artist', 'artists', 'status')
        break
      case 'logs': {
        const last = logs.value.at(-1)?.id ?? 0
        const fresh = msg.data.filter(l => l.id > last)
        if (fresh.length)
          logs.value = [...logs.value, ...fresh].slice(-3000)
        break
      }
    }
  }

  function connect(qc: QueryClient) {
    client = qc
    if (socket)
      return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${proto}://${location.host}/api/ws`)
    socket.onopen = () => {
      connected.value = true
      retry = 0
    }
    socket.onmessage = e => handle(JSON.parse(e.data))
    socket.onclose = (e) => {
      connected.value = false
      socket = null
      if (e.code === 4401)
        return
      retry = Math.min(retry + 1, 6)
      setTimeout(() => client && connect(client), 500 * 2 ** retry)
    }
  }

  function disconnect() {
    socket?.close(4401)
    socket = null
  }

  function seedLogs(list: LogLine[]) {
    const known = new Set(logs.value.map(l => l.id))
    logs.value = [...list.filter(l => !known.has(l.id)), ...logs.value].sort((a, b) => a.id - b.id).slice(-3000)
  }

  function seedEvents(list: JournalEvent[]) {
    if (!events.value.length)
      events.value = list
  }

  return { engine, hunter, events, logs, unseen, transfers, connected, speedHistory, connect, disconnect, seedEvents, seedLogs }
})

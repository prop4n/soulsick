import type { Ref } from 'vue'
import type {
  AlbumDetail,
  AppSettings,
  AppStatus,
  Artist,
  ArtistDetail,
  FormatDef,
  JournalEvent,
  QualityProfile,
  StorageDisk,
  ReleaseGroup,
  Transfer,
} from '@/lib/types'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { api } from '@/lib/api'

export const useStatus = () => useQuery({
  queryKey: ['status'],
  queryFn: () => api.get<AppStatus>('/status'),
  refetchInterval: 15_000,
})

export const useArtists = () => useQuery({ queryKey: ['artists'], queryFn: () => api.get<Artist[]>('/artists') })

export const useArtist = (id: Ref<number>) => useQuery({
  queryKey: ['artist', id],
  queryFn: () => api.get<ArtistDetail>(`/artists/${id.value}`),
})

export const useAlbum = (id: Ref<number>) => useQuery({
  queryKey: ['album', id],
  queryFn: () => api.get<AlbumDetail>(`/albums/${id.value}`),
})

export const useAlbums = (status: Ref<string> | string) => useQuery({
  queryKey: ['albums', status],
  queryFn: () => api.get<ReleaseGroup[]>(`/albums?status=${typeof status === 'string' ? status : status.value}`),
})

export const useProfiles = () => useQuery({
  queryKey: ['profiles'],
  queryFn: () => api.get<QualityProfile[]>('/profiles'),
  staleTime: 60_000,
})

export const useFormats = () => useQuery({
  queryKey: ['formats'],
  queryFn: () => api.get<FormatDef[]>('/formats'),
  staleTime: Infinity,
})

export const useSettings = () => useQuery({ queryKey: ['settings'], queryFn: () => api.get<AppSettings>('/settings') })

export const useTransfers = (direction: Ref<'download' | 'upload'>) => useQuery({
  queryKey: ['transfers', direction],
  queryFn: () => api.get<Transfer[]>(`/transfers?direction=${direction.value}`),
  refetchInterval: 20_000,
})

export function useEvents(params: Ref<Record<string, string | number | undefined>>) {
  const qs = computed(() => {
    const p = new URLSearchParams()
    for (const [k, v] of Object.entries(params.value)) {
      if (v !== undefined && v !== '')
        p.set(k, String(v))
    }
    return p.toString()
  })
  return useQuery({
    queryKey: ['events', qs],
    queryFn: () => api.get<JournalEvent[]>(`/events?${qs.value}`),
  })
}

export const useStorage = () => useQuery({
  queryKey: ['storage'],
  queryFn: () => api.get<{ disks: StorageDisk[] }>('/storage'),
  staleTime: 60_000,
  refetchInterval: 5 * 60_000,
})

import type { AlbumStatus, TransferStateName } from './types'
import { t, te } from '@/i18n'

/** The chain: the four stages an album goes through, from wanted to shelved. */
export const CHAIN_STAGES = ['wanted', 'found', 'received', 'shelved'] as const

export type StageTone = 'off' | 'lit' | 'active' | 'attention' | 'done' | 'error'
export type BadgeTone = 'signal' | 'success' | 'warning' | 'danger' | 'quiet'

export interface AlbumStatusInfo {
  label: string
  badge: BadgeTone
  /** Stage reached (-1 = outside the chain) */
  stage: number
  tone: StageTone
  hint: string
}

const ALBUM_META: Record<AlbumStatus, { badge: BadgeTone, stage: number, tone: StageTone }> = {
  ignored: { badge: 'quiet', stage: -1, tone: 'off' },
  wanted: { badge: 'quiet', stage: 0, tone: 'lit' },
  searching: { badge: 'signal', stage: 0, tone: 'active' },
  pending_approval: { badge: 'warning', stage: 1, tone: 'attention' },
  downloading: { badge: 'signal', stage: 2, tone: 'active' },
  importing: { badge: 'signal', stage: 3, tone: 'active' },
  needs_review: { badge: 'warning', stage: 3, tone: 'attention' },
  imported: { badge: 'success', stage: 3, tone: 'done' },
  failed: { badge: 'danger', stage: 0, tone: 'error' },
}

export function albumStatus(s: AlbumStatus): AlbumStatusInfo {
  return { ...ALBUM_META[s], label: t(`albumStatus.${s}.label`), hint: t(`albumStatus.${s}.hint`) }
}

const TRANSFER_BADGE: Record<TransferStateName, BadgeTone> = {
  queued: 'quiet',
  initializing: 'signal',
  transferring: 'signal',
  paused: 'quiet',
  complete: 'success',
  failed: 'danger',
  aborted: 'quiet',
}

export function transferState(s: TransferStateName): { label: string, badge: BadgeTone } {
  return { label: t(`transferState.${s}`), badge: TRANSFER_BADGE[s] }
}

export const FORMAT_LABELS: Record<string, string> = {
  'flac-24': 'FLAC 24',
  'flac': 'FLAC',
  'alac': 'ALAC',
  'wav': 'WAV',
  'mp3-320': 'MP3 320',
  'mp3-v0': 'MP3 V0',
  'aac-256': 'AAC 256',
  'mp3-256': 'MP3 256',
  'opus': 'Opus',
  'ogg': 'Vorbis',
  'mp3-192': 'MP3 192',
  'aac': 'AAC',
  'mp3-low': 'MP3 <192',
}

export const LOSSLESS = new Set(['flac-24', 'flac', 'alac', 'wav'])

export const RELEASE_TYPES = ['album', 'ep', 'single', 'broadcast', 'other'] as const
export const SECONDARY_TYPES = ['compilation', 'live', 'remix', 'soundtrack', 'demo', 'mixtape/street', 'dj-mix', 'interview', 'spokenword'] as const

/** Label of a MusicBrainz primary or secondary release type. */
export function releaseTypeLabel(key: string): string {
  const k = `releaseType.${key}`
  return te(k) ? t(k) : key
}

/** Journal event families, for filters and labels. */
export const EVENT_FAMILIES = ['hunt', 'search', 'download', 'import', 'upload', 'library', 'artist', 'album', 'musicbrainz', 'share', 'transfer', 'chat', 'slsk', 'settings', 'auth'] as const

export function eventFamilyLabel(family: string): string {
  const k = `eventFamily.${family === 'shares' ? 'share' : family}`
  return te(k) ? t(k) : family
}

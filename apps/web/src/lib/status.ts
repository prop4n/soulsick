import type { AlbumStatus, TransferStateName } from './types'

/** La chaîne : les quatre étapes qu'un album traverse, de « recherché » à « rangé ». */
export const CHAIN_STAGES = ['Recherché', 'Trouvé', 'Reçu', 'Rangé'] as const

export type StageTone = 'off' | 'lit' | 'active' | 'attention' | 'done' | 'error'

export interface AlbumStatusInfo {
  label: string
  badge: 'signal' | 'success' | 'warning' | 'danger' | 'quiet'
  /** Étape atteinte (-1 = hors chaîne) */
  stage: number
  tone: StageTone
  hint: string
}

export const ALBUM_STATUS: Record<AlbumStatus, AlbumStatusInfo> = {
  ignored: { label: 'Non suivi', badge: 'quiet', stage: -1, tone: 'off', hint: 'Soulsick ne cherche pas cet album.' },
  wanted: { label: 'Recherché', badge: 'quiet', stage: 0, tone: 'lit', hint: 'En attente de la prochaine chasse.' },
  searching: { label: 'Recherche…', badge: 'signal', stage: 0, tone: 'active', hint: 'Requêtes en cours sur le réseau.' },
  pending_approval: { label: 'À valider', badge: 'warning', stage: 1, tone: 'attention', hint: 'Des candidats attendent ton choix.' },
  downloading: { label: 'Téléchargement', badge: 'signal', stage: 2, tone: 'active', hint: 'Fichiers en cours de réception.' },
  importing: { label: 'Import…', badge: 'signal', stage: 3, tone: 'active', hint: 'Tags, renommage et rangement.' },
  needs_review: { label: 'À vérifier', badge: 'warning', stage: 3, tone: 'attention', hint: 'Association fichiers ↔ pistes incertaine.' },
  imported: { label: 'Dans la bibliothèque', badge: 'success', stage: 3, tone: 'done', hint: 'Présent dans /music.' },
  failed: { label: 'Échec', badge: 'danger', stage: 0, tone: 'error', hint: 'Le dernier essai a échoué.' },
}

export const TRANSFER_STATE: Record<TransferStateName, { label: string, badge: AlbumStatusInfo['badge'] }> = {
  queued: { label: 'En file', badge: 'quiet' },
  initializing: { label: 'Connexion', badge: 'signal' },
  transferring: { label: 'En cours', badge: 'signal' },
  paused: { label: 'En pause', badge: 'quiet' },
  complete: { label: 'Terminé', badge: 'success' },
  failed: { label: 'Échec', badge: 'danger' },
  aborted: { label: 'Annulé', badge: 'quiet' },
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

export const RELEASE_TYPES: Record<string, string> = {
  album: 'Albums',
  ep: 'EP',
  single: 'Singles',
  broadcast: 'Diffusions',
  other: 'Autres',
}

export const SECONDARY_TYPES: Record<string, string> = {
  'compilation': 'Compilations',
  'live': 'Live',
  'remix': 'Remix',
  'soundtrack': 'BO',
  'demo': 'Démos',
  'mixtape/street': 'Mixtapes',
  'dj-mix': 'DJ mix',
  'interview': 'Interviews',
  'spokenword': 'Texte lu',
}

/** Familles d'événements du journal, pour les filtres et les pictos. */
export const EVENT_FAMILIES: Record<string, string> = {
  hunt: 'Chasse',
  search: 'Recherches',
  download: 'Téléchargements',
  upload: 'Partage',
  import: 'Import',
  library: 'Bibliothèque',
  artist: 'Artistes',
  album: 'Albums',
  musicbrainz: 'MusicBrainz',
  slsk: 'Réseau',
  share: 'Partages',
  shares: 'Partages',
  settings: 'Réglages',
  auth: 'Sécurité',
}

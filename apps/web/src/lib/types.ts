export type AlbumStatus =
  | 'ignored'
  | 'wanted'
  | 'searching'
  | 'pending_approval'
  | 'downloading'
  | 'importing'
  | 'needs_review'
  | 'imported'
  | 'failed'

export type ArtistMode = 'auto' | 'validation'

export interface EngineStatus {
  configured: boolean
  connected: boolean
  connecting: boolean
  username: string | null
  error: string | null
  download_speed: number
  upload_speed: number
  free_upload_slots: number
  upload_slots: number
  shared_folders: number
  shared_files: number
}

export interface HunterState {
  current: { release_group_id: number, label: string, step: string, query?: string } | null
  last_run_at: string | null
  next_run_at: string | null
}

export interface AppStatus {
  engine: EngineStatus
  hunter: HunterState
  library: { files: number, size: number, scanning: boolean }
  artists: number
  albums: Partial<Record<AlbumStatus, number>>
  attention: number
  active_transfers: { download: number, upload: number }
  paths: { music: string, downloads: string, config: string }
}

export interface QualityProfile {
  id: number
  name: string
  formats: string[]
  upgrade_until: string | null
  max_missing_tracks: number
}

export interface FormatDef { key: string, label: string }

export interface ArtistStats {
  total: number
  monitored: number
  imported: number
  wanted: number
  attention: number
  cover_mbid?: string
}

export interface Artist {
  id: number
  mbid: string
  name: string
  sort_name: string
  disambiguation: string
  country: string | null
  type: string | null
  monitored: boolean
  mode: ArtistMode
  quality_profile_id: number | null
  primary_types: string[]
  secondary_types: string[]
  added_at: string
  last_synced_at: string | null
  stats: ArtistStats
}

export interface ReleaseGroup {
  id: number
  mbid: string
  artist_id: number
  title: string
  primary_type: string | null
  secondary_types: string[]
  first_release_date: string | null
  monitored: boolean
  status: AlbumStatus
  status_reason: string | null
  selected_release_id: number | null
  imported_format: string | null
  imported_path: string | null
  last_searched_at: string | null
  updated_at: string
  artist?: { id: number, name: string, mbid: string, mode: ArtistMode }
}

export interface ArtistDetail extends Artist {
  release_groups: ReleaseGroup[]
}

export interface Track {
  id: number
  mbid: string
  recording_mbid: string
  disc: number
  position: number
  number: string
  title: string
  artist_credit: string
  length_ms: number | null
}

export interface Release {
  id: number
  mbid: string
  title: string
  date: string | null
  country: string | null
  status: string | null
  disambiguation: string
  formats: string
  track_count: number
  disc_count: number
  label: string | null
  barcode: string | null
  tracks: Track[]
}

export interface RemoteFile {
  filename: string
  size: number
  bitrate: number | null
  duration: number | null
  sample_rate: number | null
  bit_depth: number | null
  vbr: boolean
  format: string | null
  extra?: boolean
  name?: string
}

export interface ScoreDetail {
  format?: { points: number, max: number, format: string | null, label: string, rank: number | null, mixed: boolean }
  match?: {
    points: number
    max: number
    release: string
    release_id: number
    tracks_expected: number
    tracks_found: number
    tracks_matched: number
    title_score: number
    duration_score: number | null
    confidence: number
    missing: string[]
  }
  peer?: { points: number, max: number, free_slot: boolean, queue_size: number, avg_speed: number }
}

export interface PlanItem {
  file: string
  name: string
  format: string | null
  duration: number | null
  track_id: number | null
  track_title: string | null
  disc: number | null
  position: number | null
  score: number | null
}

export interface Candidate {
  id: number
  release_group_id: number
  search_run_id: number | null
  username: string
  directory: string
  files: RemoteFile[]
  format: string | null
  score: number
  score_detail: ScoreDetail
  status: 'proposed' | 'rejected' | 'chosen' | 'downloaded' | 'failed' | 'imported'
  reject_reason: string | null
  matched_release_id: number | null
  has_free_slots: boolean
  queue_size: number
  avg_speed: number
  download_dir: string | null
  import_plan: PlanItem[] | null
  created_at: string
}

export interface SearchRun {
  id: number
  query: string
  kind: string
  started_at: string
  result_count: number
  peer_count: number
}

export interface LibraryFile {
  id: number
  path: string
  size: number
  format: string | null
  bitrate: number | null
  duration: number | null
  tag_artist: string | null
  tag_album: string | null
  tag_title: string | null
  release_group_mbid: string | null
  release_mbid: string | null
  recording_mbid: string | null
}

export type TransferStateName = 'queued' | 'initializing' | 'transferring' | 'paused' | 'complete' | 'failed' | 'aborted'

export interface Transfer {
  id: number
  direction: 'download' | 'upload'
  username: string
  remote_path: string
  local_path: string | null
  size: number | null
  bytes_transferred: number
  speed: number
  state: TransferStateName
  place_in_queue: number | null
  remotely_queued?: boolean
  error: string | null
  attempts: number
  candidate_id: number | null
  release_group_id: number | null
  created_at: string | null
  started_at: string | null
  completed_at: string | null
}

export interface JournalEvent {
  id: number
  ts: string
  kind: string
  level: 'info' | 'warning' | 'error'
  message: string
  artist_id: number | null
  release_group_id: number | null
  transfer_id: number | null
  candidate_id: number | null
  data: Record<string, unknown>
}

export interface AlbumDetail extends ReleaseGroup {
  releases: Release[]
  candidates: Candidate[]
  search_runs: SearchRun[]
  files: LibraryFile[]
  transfers: Transfer[]
  events: JournalEvent[]
}

export interface MBArtist {
  mbid: string
  name: string
  sort_name: string
  disambiguation: string
  country: string | null
  type: string | null
  score: number
  begin: string | null
  tags: string[]
  in_library: boolean
}

export interface SearchFolder {
  username: string
  directory: string
  files: RemoteFile[]
  formats: string[]
  audio_count: number
  size: number
  has_free_slots: boolean
  avg_speed: number
  queue_size: number
}

export interface SearchSnapshot {
  ticket: number
  query: string
  elapsed: number
  peer_count: number
  file_count: number
  folders: SearchFolder[]
  responses?: SearchResponse[]
}

export interface Share {
  id: number
  path: string
  enabled: boolean
  allowed_extensions: string[]
  exclude_patterns: string[]
  file_count: number
  total_size: number
  excluded_count: number
  last_scan_at: string | null
  exists: boolean
}

export interface SharePreview {
  exists: boolean
  included: number
  included_size?: number
  excluded: number
  excluded_samples: { path: string, reason: string }[]
  extensions: Record<string, number>
  effective_extensions?: string[]
}

export interface BrowseDirectory { path: string, files: (RemoteFile & { name: string })[] }

export interface AppSettings {
  soulseek: {
    username: string
    password: string
    listen_port: number
    upnp: boolean
    upload_slots: number
    upload_speed_kbps: number
    download_speed_kbps: number
    share_library: boolean
    description: string
  }
  hunter: {
    enabled: boolean
    interval_minutes: number
    max_searches_per_run: number
    search_wait_seconds: number
    proposals: number
    min_match: number
    download_covers: boolean
  }
  library: {
    naming_template: string
    sync_interval_hours: number
    write_tags: boolean
    embed_cover: boolean
  }
  navidrome: { enabled: boolean, url: string, username: string, password: string }
}

export interface CoverageSource {
  candidate_id: number
  username: string
  transfer_id: number
  state: TransferStateName
  format: string | null
  filename: string
  bytes: number
  size: number | null
}

export interface CoverageTrack {
  track_id: number
  disc: number
  position: number
  title: string
  length_ms: number | null
  state: 'received' | 'downloading' | 'missing' | 'in_library'
  sources: CoverageSource[]
}

export interface CoverageFiller {
  candidate_id: number
  username: string
  directory: string
  format: string | null
  score: number
  status: string
  has_free_slots: boolean
  queue_size: number
  avg_speed: number
  tracks: { track_id: number, title: string, filename: string, format: string | null }[]
}

export interface Coverage {
  release_id: number | null
  release_title?: string
  tracks: CoverageTrack[]
  summary: { received: number, downloading: number, missing: number, in_library: number, total: number }
  received_formats?: string[]
  fillers: CoverageFiller[]
}

export interface LogLine {
  id: number
  ts: string
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical'
  source: string
  logger: string
  message: string
}

export interface SearchResponse {
  at: number
  username: string
  files: number
  folders: number
  locked: number
  free_slot: boolean
  speed: number
  queue: number
}

export interface Activity {
  hunter: HunterState
  searches: { ticket: number, query: string, age: number, responses: number, files: number }[]
  library_scanning: boolean
  retrying: number
  engine: EngineStatus
}

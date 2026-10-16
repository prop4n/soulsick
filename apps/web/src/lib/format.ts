const nf = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })

export function bytes(n: number | null | undefined): string {
  if (n == null)
    return '—'
  const units = ['o', 'Ko', 'Mo', 'Go', 'To']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${nf.format(v)} ${units[i]}`
}

export function speed(bps: number | null | undefined): string {
  if (!bps)
    return '0 o/s'
  return `${bytes(bps)}/s`
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null)
    return '—'
  const s = Math.round(seconds)
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

export function ms(msValue: number | null | undefined): string {
  return msValue == null ? '—' : duration(msValue / 1000)
}

const rtf = new Intl.RelativeTimeFormat('fr', { numeric: 'auto' })

export function ago(iso: string | null | undefined): string {
  if (!iso)
    return 'jamais'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 45)
    return diff < 0 ? 'à l’instant' : 'dans un instant'
  if (abs < 3600)
    return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400)
    return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30)
    return rtf.format(Math.round(diff / 86400), 'day')
  return new Date(iso).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function dayLabel(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const y = new Date(Date.now() - 86400000)
  if (d.toDateString() === today.toDateString())
    return 'Aujourd’hui'
  if (d.toDateString() === y.toDateString())
    return 'Hier'
  return d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' })
}

export function year(date: string | null | undefined): string {
  return date ? date.slice(0, 4) : '—'
}

/** Sépare un chemin Soulseek/local en dossier + nom de fichier. */
export function splitPath(path: string): { dir: string, name: string } {
  const norm = path.replace(/\\/g, '/')
  const i = norm.lastIndexOf('/')
  return i < 0 ? { dir: '', name: norm } : { dir: norm.slice(0, i), name: norm.slice(i + 1) }
}

export function plural(n: number, one: string, many?: string): string {
  return `${n} ${n > 1 ? (many ?? `${one}s`) : one}`
}

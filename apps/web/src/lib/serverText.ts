import type { JournalEvent } from './types'
import { locale, t, te } from '@/i18n'

/** A sentence written by the server: key + params (params may nest other sentences). */
export interface ServerMsg { key: string, params?: Record<string, unknown> }

function isMsg(v: unknown): v is ServerMsg {
  return !!v && typeof v === 'object' && typeof (v as ServerMsg).key === 'string'
}

function value(v: unknown): unknown {
  if (isMsg(v))
    return translate(v) ?? ''
  if (Array.isArray(v))
    return v.map(x => (isMsg(x) ? translate(x) ?? '' : String(x))).join('')
  return v
}

/** Translated text, or null when this locale has no version of the key. */
function translate(m: ServerMsg): string | null {
  const k = `server.${m.key}`
  if (!te(k))
    return null
  const params = Object.fromEntries(Object.entries(m.params ?? {}).map(([p, v]) => [p, value(v)]))
  return typeof params.n === 'number' ? t(k, params, params.n) : t(k, params)
}

/**
 * Text of a server message in the current locale. English is what the server
 * already rendered (`fallback`); other locales use their own templates when they exist.
 */
export function serverText(fallback: string | null | undefined, m: ServerMsg | null | undefined): string {
  if (locale() === 'en' || !m)
    return fallback ?? ''
  return translate(m) ?? fallback ?? ''
}

export function eventText(e: JournalEvent): string {
  return serverText(e.message, (e.data as { _t?: ServerMsg } | null)?._t)
}

/** Raw event data without the translation envelope. */
export function eventData(e: JournalEvent): Record<string, unknown> {
  const { _t, ...rest } = (e.data ?? {}) as Record<string, unknown>
  return rest
}

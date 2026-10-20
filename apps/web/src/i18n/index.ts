import { createI18n } from 'vue-i18n'
import en from './en'
import fr from './fr'
import serverFr from './server.fr'

export type Locale = 'en' | 'fr'
export type LocalePref = Locale | 'auto'
export const LOCALES: { value: Locale, label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
]

const KEY = 'soulsick.locale'

export function getLocalePref(): LocalePref {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'en' || v === 'fr')
      return v
  }
  catch {}
  return 'auto'
}

function resolve(pref: LocalePref): Locale {
  if (pref !== 'auto')
    return pref
  return navigator.language?.toLowerCase().startsWith('fr') ? 'fr' : 'en'
}

/** "a.b.c" keys → nested objects (vue-i18n resolves paths by dots). */
function unflatten(flat: Record<string, string>) {
  const out: Record<string, any> = {}
  for (const [k, v] of Object.entries(flat)) {
    const parts = k.split('.')
    let node = out
    for (const p of parts.slice(0, -1))
      node = (node[p] ??= {})
    node[parts.at(-1)!] = v
  }
  return out
}

/** French: 0 and 1 are singular ("0 fichier"). */
function frPlural(choice: number, choicesLength: number) {
  const n = Math.abs(choice)
  if (choicesLength === 2)
    return n > 1 ? 1 : 0
  return n === 0 ? 0 : n === 1 ? 1 : 2
}

export const i18n = createI18n({
  legacy: false,
  locale: resolve(getLocalePref()),
  fallbackLocale: 'en',
  // English server messages come rendered from the server; other locales translate them by key
  messages: { en, fr: { ...fr, server: unflatten(serverFr) } } as any,
  pluralRules: { fr: frPlural },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: false,
})

document.documentElement.lang = i18n.global.locale.value

export function setLocalePref(pref: LocalePref) {
  try {
    if (pref === 'auto')
      localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  }
  catch {}
  const l = resolve(pref)
  i18n.global.locale.value = l
  document.documentElement.lang = l
}

export function locale(): Locale {
  return i18n.global.locale.value as Locale
}

/** BCP 47 tag for Intl formatters. */
export function intlLocale(): string {
  return locale() === 'fr' ? 'fr-FR' : 'en-GB'
}

/**
 * Translation outside components (lib/, stores/). Keys are often built at run time,
 * so a plain signature is used rather than vue-i18n's (very deep) typed one.
 */
export const t = i18n.global.t as unknown as (key: string, named?: Record<string, unknown> | number, plural?: number) => string
export const te = i18n.global.te as unknown as (key: string) => boolean

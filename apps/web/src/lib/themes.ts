import { t as msg } from '@/i18n'
/**
 * Thèmes Soulsick : un thème est un petit objet JSON.
 *
 * Forme courte (le reste est calculé) :
 *   { "id": "mon-theme", "name": "Mon thème",
 *     "base": { "hue": 295, "chroma": 0.01 },
 *     "accent": { "dark": "oklch(0.82 0.11 298)", "light": "oklch(0.52 0.19 290)" } }
 *
 * Forme détaillée : en plus, "dark" et "light" peuvent surcharger n'importe quel rôle
 * (voir TOKENS), avec toute couleur CSS valide (#hex, rgb(), hsl(), oklch()…).
 * Options : "radius" (ex. "0.75rem"), "coverAccent" (accent tiré des pochettes, true par défaut).
 */

export const TOKENS = [
  'background',
  'card',
  'popover',
  'well',
  'foreground',
  'muted',
  'mutedForeground',
  'faint',
  'primary',
  'primaryForeground',
  'secondary',
  'secondaryForeground',
  'accent',
  'destructive',
  'success',
  'warning',
  'border',
  'borderStrong',
  'input',
  'ring',
] as const

export type Token = typeof TOKENS[number]
export type Palette = Record<Token, string>

export interface ThemeDef {
  id: string
  name: string
  description?: string
  author?: string
  radius?: string
  coverAccent?: boolean
  base?: { hue: number, chroma?: number }
  accent?: { dark?: string, light?: string, darkForeground?: string, lightForeground?: string }
  dark?: Partial<Palette>
  light?: Partial<Palette>
}

const r = (n: number) => Math.round(n * 1000) / 1000
const ok = (l: number, c: number, h: number, a?: number) =>
  `oklch(${r(l)} ${r(Math.min(c, 0.37))} ${Math.round(h)}${a != null ? ` / ${a}%` : ''})`

/** Palette complète d'un thème pour un mode : base tonale calculée, puis surcharges. */
export function palette(def: ThemeDef, mode: 'dark' | 'light'): Palette {
  const h = def.base?.hue ?? 295
  const c = def.base?.chroma ?? 0.01
  const acc = def.accent ?? {}
  const base: Palette = mode === 'dark'
    ? {
        background: ok(0.145, c * 0.8, h),
        card: ok(0.185, c * 1.4, h),
        popover: ok(0.215, c * 1.8, h),
        well: ok(0.125, c * 0.8, h),
        foreground: ok(0.95, c, h),
        muted: ok(0.23, c * 2, h),
        mutedForeground: ok(0.74, c * 2.5, h),
        faint: ok(0.56, c * 2.5, h),
        primary: acc.dark ?? ok(0.82, 0.11, h),
        primaryForeground: acc.darkForeground ?? ok(0.22, 0.06, h),
        secondary: ok(0.26, c * 3.5, h),
        secondaryForeground: ok(0.9, c * 4, h),
        accent: ok(0.255, c * 3, h),
        destructive: ok(0.72, 0.16, 22),
        success: ok(0.8, 0.12, 165),
        warning: ok(0.82, 0.11, 60),
        border: ok(0.95, c * 3, h, 8),
        borderStrong: ok(0.95, c * 3, h, 15),
        input: ok(0.95, c * 3, h, 12),
        ring: acc.dark ?? ok(0.82, 0.11, h),
      }
    : {
        background: ok(0.975, c * 0.6, h),
        card: ok(0.993, c * 0.3, h),
        popover: ok(0.995, c * 0.3, h),
        well: ok(0.945, c * 1.2, h),
        foreground: ok(0.22, c * 2.5, h),
        muted: ok(0.94, c * 1.2, h),
        mutedForeground: ok(0.47, c * 3, h),
        faint: ok(0.62, c * 2.5, h),
        primary: acc.light ?? ok(0.52, 0.17, h),
        primaryForeground: acc.lightForeground ?? ok(0.99, 0.005, h),
        secondary: ok(0.93, c * 2.5, h),
        secondaryForeground: ok(0.3, c * 6, h),
        accent: ok(0.93, c * 2.5, h),
        destructive: ok(0.58, 0.2, 22),
        success: ok(0.56, 0.12, 165),
        warning: ok(0.62, 0.15, 55),
        border: ok(0.3, c * 4, h, 10),
        borderStrong: ok(0.3, c * 4, h, 20),
        input: ok(0.3, c * 4, h, 15),
        ring: acc.light ?? ok(0.52, 0.17, h),
      }
  const over = (mode === 'dark' ? def.dark : def.light) ?? {}
  const out = { ...base, ...over }
  if (over.primary && !over.ring)
    out.ring = over.primary
  return out
}

const kebab = (s: string) => s.replace(/[A-Z]/g, m => `-${m.toLowerCase()}`)

/** Theme stylesheet (variables on :root and .dark). */
export function themeCss(def: ThemeDef): string {
  const block = (p: Palette) => TOKENS.map(t => `  --${kebab(t)}: ${p[t]};`).join('\n')
  const radius = def.radius ? `  --radius: ${def.radius};\n` : ''
  return `:root {\n${radius}${block(palette(def, 'light'))}\n}\n.dark {\n${block(palette(def, 'dark'))}\n}\n`
}

/** Validates a user theme: only valid CSS colours get through. */
export function validateTheme(input: unknown): { theme?: ThemeDef, errors: string[] } {
  const errors: string[] = []
  if (typeof input !== 'object' || input === null || Array.isArray(input))
    return { errors: [msg('themes.errors.notObject')] }
  const t = input as Record<string, unknown>
  if (typeof t.id !== 'string' || !/^[a-z0-9][a-z0-9-]{1,40}$/.test(t.id))
    errors.push(msg('themes.errors.id'))
  if (typeof t.name !== 'string' || !t.name.trim() || t.name.length > 60)
    errors.push(msg('themes.errors.name'))
  const isColor = (v: unknown) => typeof v === 'string' && v.length < 80 && CSS.supports('color', v)
  if (t.base !== undefined) {
    const b = t.base as Record<string, unknown>
    if (typeof b !== 'object' || b === null || typeof b.hue !== 'number' || b.hue < 0 || b.hue > 360)
      errors.push(msg('themes.errors.hue'))
    if (b && b.chroma !== undefined && (typeof b.chroma !== 'number' || b.chroma < 0 || b.chroma > 0.08))
      errors.push(msg('themes.errors.chroma'))
  }
  if (t.accent !== undefined) {
    if (typeof t.accent !== 'object' || t.accent === null)
      errors.push(msg('themes.errors.accent'))
    else {
      for (const [k, v] of Object.entries(t.accent)) {
        if (!['dark', 'light', 'darkForeground', 'lightForeground'].includes(k))
          errors.push(msg('themes.errors.accentKey', { key: `accent.${k}` }))
        else if (!isColor(v))
          errors.push(msg('themes.errors.color', { key: `accent.${k}`, value: String(v) }))
      }
    }
  }
  for (const mode of ['dark', 'light'] as const) {
    const m = t[mode]
    if (m === undefined)
      continue
    if (typeof m !== 'object' || m === null) {
      errors.push(msg('themes.errors.mode', { key: mode }))
      continue
    }
    for (const [k, v] of Object.entries(m)) {
      if (!(TOKENS as readonly string[]).includes(k))
        errors.push(msg('themes.errors.role', { key: `${mode}.${k}`, roles: TOKENS.join(', ') }))
      else if (!isColor(v))
        errors.push(msg('themes.errors.color', { key: `${mode}.${k}`, value: String(v) }))
    }
  }
  if (t.radius !== undefined && (typeof t.radius !== 'string' || !/^(0|\d*\.?\d+(rem|px))$/.test(t.radius)))
    errors.push(msg('themes.errors.radius'))
  if (t.coverAccent !== undefined && typeof t.coverAccent !== 'boolean')
    errors.push(msg('themes.errors.coverAccent'))
  for (const k of ['description', 'author']) {
    if (t[k] !== undefined && (typeof t[k] !== 'string' || (t[k] as string).length > 200))
      errors.push(msg('themes.errors.text', { key: k }))
  }
  const known = ['id', 'name', 'description', 'author', 'radius', 'coverAccent', 'base', 'accent', 'dark', 'light']
  for (const k of Object.keys(t)) {
    if (!known.includes(k))
      errors.push(msg('themes.errors.unknown', { key: k }))
  }
  return errors.length ? { errors } : { theme: t as unknown as ThemeDef, errors }
}

/** Built-in themes. */
export const BUILTIN_THEMES: ThemeDef[] = [
  {
    id: 'symfonium',
    name: 'Symfonium',
    description: 'Near-black with a hint of violet, lavender accent; the accent follows the covers.',
    radius: '0.75rem',
    coverAccent: true,
    base: { hue: 295, chroma: 0.01 },
    accent: { dark: 'oklch(0.82 0.11 298)', darkForeground: 'oklch(0.24 0.08 292)', light: 'oklch(0.52 0.19 290)' },
  },
  {
    id: 'ampli',
    name: 'Amp',
    description: 'Hi-fi amp faceplate: warm black, cream, VU-meter amber.',
    radius: '0.5rem',
    coverAccent: false,
    base: { hue: 60, chroma: 0.007 },
    accent: { dark: 'oklch(0.8 0.145 72)', darkForeground: 'oklch(0.2 0.03 60)', light: 'oklch(0.66 0.15 62)' },
    dark: { foreground: 'oklch(0.935 0.018 85)', mutedForeground: 'oklch(0.7 0.016 78)', warning: 'oklch(0.74 0.15 48)', success: 'oklch(0.76 0.14 152)' },
    light: { background: 'oklch(0.972 0.008 85)', card: 'oklch(0.988 0.006 85)' },
  },
  {
    id: 'encre',
    name: 'Ink',
    description: 'Black and white, no tint. The only colour comes from the covers.',
    radius: '0.375rem',
    coverAccent: true,
    base: { hue: 250, chroma: 0.002 },
    accent: { dark: 'oklch(0.94 0 0)', darkForeground: 'oklch(0.16 0 0)', light: 'oklch(0.2 0 0)', lightForeground: 'oklch(0.98 0 0)' },
  },
  {
    id: 'bande',
    name: 'Tape',
    description: 'Tape brown, oxide rust, cream label.',
    radius: '0.5rem',
    coverAccent: false,
    base: { hue: 45, chroma: 0.016 },
    accent: { dark: 'oklch(0.72 0.14 42)', darkForeground: 'oklch(0.18 0.03 40)', light: 'oklch(0.55 0.15 40)' },
    dark: { warning: 'oklch(0.84 0.12 88)', foreground: 'oklch(0.93 0.025 80)' },
    light: { warning: 'oklch(0.6 0.14 80)', background: 'oklch(0.965 0.014 75)' },
  },
  {
    id: 'foret',
    name: 'Night forest',
    description: 'Deep green-black, sage accent.',
    radius: '0.75rem',
    coverAccent: true,
    base: { hue: 160, chroma: 0.012 },
    accent: { dark: 'oklch(0.83 0.09 145)', darkForeground: 'oklch(0.2 0.04 150)', light: 'oklch(0.5 0.1 150)' },
    dark: { success: 'oklch(0.82 0.1 185)' },
    light: { success: 'oklch(0.52 0.1 190)' },
  },
]

/**
 * Checks translations:
 * - every key used in the code exists in en.ts;
 * - fr.ts / server.fr.ts compile, and use only params the reference text has;
 * - server.fr.ts covers exactly the keys of apps/api/src/soulsick/messages.py.
 * Run: bun run check:i18n
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { baseCompile } from '@intlify/message-compiler'
import en from '../src/i18n/en'
import fr from '../src/i18n/fr'
import serverFr from '../src/i18n/server.fr'

const root = join(import.meta.dir, '..')
const problems: string[] = []

function flat(o: Record<string, unknown>, p = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(o)) {
    const key = p ? `${p}.${k}` : k
    if (typeof v === 'string')
      out[key] = v
    else Object.assign(out, flat(v as Record<string, unknown>, key))
  }
  return out
}
const params = (s: string) => new Set([...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]))

function compiles(name: string, k: string, v: string) {
  try {
    baseCompile(v, { onError: (e) => { throw e } })
  }
  catch (e) {
    problems.push(`${name} ${k}: ${(e as Error).message}`)
  }
}

const E = flat(en)
const F = flat(fr)
for (const [k, v] of Object.entries(E)) compiles('en', k, v)
for (const [k, v] of Object.entries(F)) {
  compiles('fr', k, v)
  for (const p of params(v)) {
    if (!params(E[k] ?? '').has(p))
      problems.push(`fr ${k}: unknown param {${p}}`)
  }
}

// Keys used in the code
function walk(d: string): string[] {
  return readdirSync(d).flatMap((f) => {
    const p = join(d, f)
    return statSync(p).isDirectory() ? (f === 'i18n' ? [] : walk(p)) : /\.(vue|ts)$/.test(f) ? [p] : []
  })
}
for (const f of walk(join(root, 'src'))) {
  const s = readFileSync(f, 'utf8')
  for (const m of s.matchAll(/\b(?:t|msg)\(\s*(['"])([\w.\-/]+)\1/g)) {
    if (!(m[2]! in E))
      problems.push(`missing in en: ${m[2]} (${f.replace(root, '')})`)
  }
}

// Server messages
const py = readFileSync(join(root, '../api/src/soulsick/messages.py'), 'utf8')
const server = Object.fromEntries([...py.matchAll(/^\s+"([\w.]+)": "(.*)",$/gm)].map(m => [m[1]!, m[2]!]))
for (const k of Object.keys(server)) {
  if (!(k in serverFr))
    problems.push(`server.fr.ts missing: ${k}`)
}
for (const [k, v] of Object.entries(serverFr)) {
  if (!(k in server)) {
    problems.push(`server.fr.ts has unknown key: ${k}`)
    continue
  }
  compiles('server.fr', k, v)
  for (const p of params(v)) {
    if (!params(server[k]!).has(p))
      problems.push(`server.fr ${k}: unknown param {${p}}`)
  }
  if (server[k]!.includes(' | ') !== v.includes(' | '))
    problems.push(`server.fr ${k}: plural forms differ from the server`)
}

for (const p of problems) console.log(p)
console.log(`${Object.keys(E).length} UI keys, ${Object.keys(server).length} server keys, ${problems.length} problem(s)`)
process.exit(problems.length ? 1 : 0)

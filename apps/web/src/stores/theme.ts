import type { ThemeDef } from '@/lib/themes'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/lib/api'
import { BUILTIN_THEMES, themeCss } from '@/lib/themes'

const KEY = 'soulsick-theme-def'

function inject(def: ThemeDef) {
  let el = document.getElementById('soulsick-theme') as HTMLStyleElement | null
  if (!el) {
    el = document.createElement('style')
    el.id = 'soulsick-theme'
    document.head.appendChild(el)
  }
  el.textContent = themeCss(def)
}

/** Thème appliqué au démarrage, avant même la connexion (copie gardée dans ce navigateur). */
export function bootTheme() {
  try {
    const raw = localStorage.getItem(KEY)
    inject(raw ? JSON.parse(raw) : BUILTIN_THEMES[0]!)
  }
  catch {
    inject(BUILTIN_THEMES[0]!)
  }
}

export const useThemes = defineStore('themes', () => {
  const custom = ref<ThemeDef[]>([])
  const current = ref<ThemeDef>(readCurrent())
  const previewing = ref<ThemeDef | null>(null)

  const all = computed(() => [...BUILTIN_THEMES, ...custom.value])
  const isBuiltin = (id: string) => BUILTIN_THEMES.some(t => t.id === id)
  /** L'accent tiré des pochettes est-il voulu par le thème affiché ? */
  const coverAccent = computed(() => (previewing.value ?? current.value).coverAccent !== false)

  function readCurrent(): ThemeDef {
    try {
      const raw = localStorage.getItem(KEY)
      return raw ? JSON.parse(raw) : BUILTIN_THEMES[0]!
    }
    catch {
      return BUILTIN_THEMES[0]!
    }
  }

  async function load() {
    custom.value = await api.get<ThemeDef[]>('/themes')
    // Le thème actif a pu être modifié depuis un autre appareil
    const fresh = all.value.find(t => t.id === current.value.id)
    if (fresh)
      select(fresh)
  }

  function select(def: ThemeDef) {
    current.value = def
    previewing.value = null
    try {
      localStorage.setItem(KEY, JSON.stringify(def))
    }
    catch {}
    inject(def)
  }

  function preview(def: ThemeDef | null) {
    previewing.value = def
    inject(def ?? current.value)
  }

  async function save(def: ThemeDef) {
    const list = [...custom.value.filter(t => t.id !== def.id), def]
    custom.value = await api.put<ThemeDef[]>('/themes', list)
    select(def)
  }

  async function remove(id: string) {
    custom.value = await api.put<ThemeDef[]>('/themes', custom.value.filter(t => t.id !== id))
    if (current.value.id === id)
      select(BUILTIN_THEMES[0]!)
  }

  return { custom, current, previewing, all, coverAccent, isBuiltin, load, select, preview, save, remove }
})

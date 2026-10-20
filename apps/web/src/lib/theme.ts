/** Apparence : suit le système par défaut, ou forcée en clair / sombre (préférence locale au navigateur). */
export type ThemePref = 'system' | 'light' | 'dark'

const KEY = 'soulsick-theme'
const media = () => window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  }
  catch {
    return 'system'
  }
}

export function applyTheme(pref: ThemePref = getTheme()) {
  const dark = pref === 'dark' || (pref === 'system' && media().matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(pref: ThemePref) {
  try {
    if (pref === 'system')
      localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
  }
  catch {}
  applyTheme(pref)
}

export function followSystemTheme() {
  media().addEventListener('change', () => {
    if (getTheme() === 'system')
      applyTheme('system')
  })
}

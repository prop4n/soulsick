import type { Ref } from 'vue'
import { computed, ref, watch } from 'vue'
import { coverUrl } from '@/lib/api'
import { useThemes } from '@/stores/theme'

/**
 * Couleur d'accent tirée de la pochette (comme Symfonium) : on échantillonne la miniature,
 * on garde la teinte la plus vive, et on la décline en clair/sombre via CSS (classe .cover-accent).
 * Pochette grise ou absente : on garde l'accent du thème.
 */
export function useCoverAccent(mbid: Ref<string | null | undefined>) {
  const hs = ref<{ h: number, s: number } | null>(null)
  const themes = useThemes()

  watch(mbid, (id) => {
    hs.value = null
    if (!id)
      return
    const img = new Image()
    img.decoding = 'async'
    img.onload = () => {
      hs.value = dominantHue(img)
    }
    img.src = coverUrl(id, 250)!
  }, { immediate: true })

  // Le thème peut désactiver l'accent tiré des pochettes (« coverAccent »: false)
  const on = computed(() => !!hs.value && themes.coverAccent)
  const style = computed(() =>
    on.value ? { '--cover-h': `${hs.value!.h}`, '--cover-s': `${hs.value!.s}%` } : undefined,
  )
  return { style, active: on }
}

function dominantHue(img: HTMLImageElement): { h: number, s: number } | null {
  const size = 32
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx)
    return null
  ctx.drawImage(img, 0, 0, size, size)
  const { data } = ctx.getImageData(0, 0, size, size)
  // Moyenne circulaire des teintes, pondérée par la saturation (les pixels ternes comptent peu)
  let x = 0
  let y = 0
  let wsum = 0
  let ssum = 0
  for (let i = 0; i < data.length; i += 4) {
    const [r, g, b] = [data[i]! / 255, data[i + 1]! / 255, data[i + 2]! / 255]
    const max = Math.max(r, g, b)
    const min = Math.min(r, g, b)
    const l = (max + min) / 2
    const d = max - min
    if (d < 0.08 || l < 0.12 || l > 0.92)
      continue
    const s = d / (1 - Math.abs(2 * l - 1))
    let h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
    h = (h * 60 + 360) % 360
    const w = s * s
    x += Math.cos((h * Math.PI) / 180) * w
    y += Math.sin((h * Math.PI) / 180) * w
    wsum += w
    ssum += s * w
  }
  if (wsum < 8)
    return null
  const h = Math.round(((Math.atan2(y, x) * 180) / Math.PI + 360) % 360)
  // Saturation bornée : jamais criard (le thème reste sobre), jamais délavé
  const s = Math.round(Math.min(72, Math.max(38, (ssum / wsum) * 80)))
  return { h, s }
}

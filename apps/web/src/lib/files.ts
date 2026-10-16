const AUDIO = new Set(['flac', 'mp3', 'm4a', 'aac', 'ogg', 'opus', 'wav', 'aiff', 'aif', 'wma', 'alac', 'ape', 'wv'])

export function extensionOf(name: string): string {
  const base = name.replace(/\\/g, '/').split('/').pop() ?? ''
  const i = base.lastIndexOf('.')
  return i < 0 ? '' : base.slice(i + 1).toLowerCase()
}

export function isAudioName(name: string): boolean {
  return AUDIO.has(extensionOf(name))
}

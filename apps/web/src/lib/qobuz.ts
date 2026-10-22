/** Files and folders downloaded from Qobuz have their own paths (no Soulseek peer can have them) */
export const isQobuz = (path: string | null | undefined) => !!path && path.startsWith('qobuz:album-')

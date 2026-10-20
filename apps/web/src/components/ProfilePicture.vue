<script setup lang="ts">
import { ImageUpIcon, Trash2Icon, UserRoundIcon } from '@lucide/vue'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { api } from '@/lib/api'

/**
 * Your Soulseek profile picture: what peers see when they open your profile.
 * Resized here (512 px at most) so it stays light for the network.
 */
const { t } = useI18n()
const MAX_BYTES = 1_000_000
const MAX_SIDE = 512

const version = ref(Date.now())
const present = ref(true)
const busy = ref(false)
const input = ref<HTMLInputElement | null>(null)

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = () => reject(r.error)
    r.readAsDataURL(blob)
  })
}

async function shrink(file: File): Promise<Blob> {
  // An animated GIF would lose its animation on a canvas: kept as is when light enough
  if (file.type === 'image/gif' && file.size <= MAX_BYTES)
    return file
  const img = await createImageBitmap(file)
  const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(img.width * scale)
  canvas.height = Math.round(img.height * scale)
  canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
  img.close()
  const encode = (type: string, quality?: number) =>
    new Promise<Blob>((resolve, reject) => canvas.toBlob(b => (b ? resolve(b) : reject(new Error(t('profilePicture.unreadable')))), type, quality))
  // Transparency is kept for PNG/WebP; photos go to JPEG
  const out = await encode(['image/png', 'image/webp'].includes(file.type) ? 'image/png' : 'image/jpeg', 0.9)
  return out.size <= MAX_BYTES ? out : encode('image/jpeg', 0.8)
}

async function pick(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!file)
    return
  busy.value = true
  try {
    const blob = await shrink(file)
    await api.put('/profile/picture', { data: await readAsDataUrl(blob) })
    present.value = true
    version.value = Date.now()
    toast.success(t('profilePicture.changed'))
  }
  catch (err) {
    toast.error((err as Error).message || t('profilePicture.unreadable'))
  }
  finally {
    busy.value = false
  }
}

async function remove() {
  busy.value = true
  try {
    await api.del('/profile/picture')
    present.value = false
    toast.success(t('profilePicture.removed'))
  }
  catch (err) {
    toast.error((err as Error).message)
  }
  finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex items-center gap-4">
    <div class="relative grid size-16 shrink-0 place-items-center overflow-hidden rounded-xl bg-muted ring-1 ring-border">
      <img
        v-if="present"
        :key="version"
        :src="`/api/profile/picture?v=${version}`"
        :alt="t('profilePicture.alt')"
        class="size-full object-cover"
        @error="present = false"
      >
      <UserRoundIcon v-else class="size-7 text-faint" />
      <div v-if="busy" class="absolute inset-0 grid place-items-center bg-background/60">
        <Spinner />
      </div>
    </div>
    <div class="flex flex-col gap-1.5">
      <div class="flex flex-wrap items-center gap-1.5">
        <Button variant="outline" size="sm" :disabled="busy" @click="input?.click()">
          <ImageUpIcon data-icon="inline-start" />
          {{ present ? t('profilePicture.change') : t('profilePicture.add') }}
        </Button>
        <Button v-if="present" variant="ghost" size="sm" class="text-muted-foreground hover:text-destructive" :disabled="busy" @click="remove">
          <Trash2Icon data-icon="inline-start" />
          {{ t('profilePicture.remove') }}
        </Button>
      </div>
      <p class="text-[12px] text-faint">
        {{ t('profilePicture.hint') }}
      </p>
    </div>
    <input ref="input" type="file" accept="image/jpeg,image/png,image/gif,image/webp" class="hidden" @change="pick">
  </div>
</template>

<script setup lang="ts">
import { PauseIcon, PlayIcon } from '@lucide/vue'
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

/** The 30-second extract of an artist's best-known track, played through soulsick. */
const props = defineProps<{ mbid: string, title: string }>()
const { t } = useI18n()
const playing = ref(false)
const progress = ref(0)
const failed = ref(false)
let audio: HTMLAudioElement | null = null

function stop() {
  audio?.pause()
  playing.value = false
}

function toggle() {
  if (failed.value)
    return
  if (playing.value)
    return stop()
  if (!audio) {
    const a = new Audio(`/api/discover/preview/${props.mbid}`)
    a.addEventListener('timeupdate', () => (progress.value = a.duration ? a.currentTime / a.duration : 0))
    a.addEventListener('ended', () => {
      playing.value = false
      progress.value = 0
    })
    a.addEventListener('error', () => {
      failed.value = true
      playing.value = false
    })
    audio = a
  }
  audio.play().then(() => (playing.value = true)).catch(() => (failed.value = true))
}

// Another card: the extract of the previous one stops
watch(() => props.mbid, () => {
  stop()
  audio = null
  progress.value = 0
  failed.value = false
})
onBeforeUnmount(stop)
defineExpose({ toggle, stop })
</script>

<template>
  <button
    type="button"
    :disabled="failed"
    class="flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors hover:bg-accent disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent"
    :aria-label="playing ? t('discover.pause') : t('discover.listen', { title })"
    @click="toggle"
  >
    <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-foreground text-background">
      <PauseIcon v-if="playing" class="size-4" />
      <PlayIcon v-else class="size-4 translate-x-px" />
    </span>
    <span class="flex min-w-0 flex-1 flex-col gap-2">
      <span class="truncate text-[13px]">{{ failed ? t('discover.noPreview') : title }}</span>
      <span class="block h-0.5 w-full overflow-hidden rounded-full bg-border">
        <span class="block h-full origin-left bg-primary" :style="{ transform: `scaleX(${progress})` }" />
      </span>
    </span>
    <span class="font-mono text-[12px] text-faint tnum">0:30</span>
  </button>
</template>

<script setup lang="ts">
import { XIcon } from '@lucide/vue'
import { ref } from 'vue'
import { cn } from '@/lib/utils'

/** Liste de valeurs courtes (extensions, motifs) saisies au clavier : Entrée ou virgule pour ajouter. */
const model = defineModel<string[]>({ required: true })
const props = defineProps<{ placeholder?: string, mono?: boolean, normalize?: (v: string) => string }>()
const draft = ref('')

function commit() {
  const parts = draft.value.split(',').map(v => (props.normalize ? props.normalize(v) : v.trim())).filter(Boolean)
  if (parts.length)
    model.value = [...new Set([...model.value, ...parts])]
  draft.value = ''
}

function remove(v: string) {
  model.value = model.value.filter(x => x !== v)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault()
    commit()
  }
  else if (e.key === 'Backspace' && !draft.value && model.value.length) {
    model.value = model.value.slice(0, -1)
  }
}
</script>

<template>
  <div class="flex min-h-9 flex-wrap items-center gap-1 rounded-md border border-input bg-well/60 px-1.5 py-1 focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30">
    <span
      v-for="v in model"
      :key="v"
      :class="cn('inline-flex h-6 items-center gap-1 rounded-[4px] border bg-card pr-1 pl-1.5 text-[12px]', mono && 'font-mono')"
    >
      {{ v }}
      <button type="button" class="text-faint hover:text-foreground" :aria-label="`Retirer ${v}`" @click="remove(v)">
        <XIcon class="size-3" />
      </button>
    </span>
    <input
      v-model="draft"
      :placeholder="model.length ? '' : placeholder"
      :class="cn('h-6 min-w-24 flex-1 bg-transparent px-1 text-[12.5px] outline-none placeholder:text-faint', mono && 'font-mono')"
      @keydown="onKey"
      @blur="commit"
    >
  </div>
</template>

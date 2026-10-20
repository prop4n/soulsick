<script setup lang="ts">
import type { ThemeDef } from '@/lib/themes'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { TOKENS, validateTheme } from '@/lib/themes'
import { useThemes } from '@/stores/theme'

/** JSON theme editor, with validation and live preview across the whole UI. */
const open = defineModel<boolean>('open', { default: false })
const props = defineProps<{ initial: ThemeDef | null, mode: 'new' | 'edit' | 'import' }>()
const { t } = useI18n()
const themes = useThemes()

const text = ref('')
const live = ref(true)
const saving = ref(false)

watch(open, (o) => {
  if (o) {
    text.value = props.initial ? JSON.stringify(props.initial, null, 2) : ''
    live.value = true
  }
  else {
    themes.preview(null)
  }
})

const parsed = computed<{ theme?: ThemeDef, errors: string[] }>(() => {
  if (!text.value.trim())
    return { errors: [] }
  try {
    return validateTheme(JSON.parse(text.value))
  }
  catch (e) {
    return { errors: [t('themes.invalidJson', { error: (e as Error).message })] }
  }
})

watch([parsed, live], ([p, l]) => {
  if (!open.value)
    return
  themes.preview(l && p.theme ? p.theme : null)
})

const clash = computed(() => {
  const th = parsed.value.theme
  if (!th)
    return null
  if (themes.isBuiltin(th.id))
    return t('themes.builtinClash', { id: th.id })
  if (props.mode !== 'edit' && themes.custom.some(c => c.id === th.id))
    return t('themes.replaceClash', { id: th.id })
  return null
})

async function save() {
  const th = parsed.value.theme
  if (!th || themes.isBuiltin(th.id))
    return
  saving.value = true
  try {
    await themes.save(th)
    toast.success(t('themes.saved', { name: th.name }))
    open.value = false
  }
  catch (e) {
    toast.error((e as Error).message)
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="flex max-h-[92svh] flex-col gap-4 sm:max-w-[720px]">
      <DialogHeader>
        <DialogTitle>{{ t(`themes.editor.${mode}`) }}</DialogTitle>
        <DialogDescription>
          {{ t('themes.editor.description') }}
        </DialogDescription>
      </DialogHeader>

      <Textarea
        v-model="text"
        spellcheck="false"
        class="scrollbar-thin min-h-[320px] flex-1 resize-none font-mono text-[12px] leading-relaxed"
        placeholder="{ &quot;id&quot;: &quot;my-theme&quot;, &quot;name&quot;: &quot;My theme&quot;, &quot;base&quot;: { &quot;hue&quot;: 200 }, &quot;accent&quot;: { &quot;dark&quot;: &quot;#7cc4ff&quot; } }"
      />

      <Alert v-if="parsed.errors.length" variant="destructive">
        <AlertTitle class="text-[13px]">
          {{ t('themes.editor.problems', parsed.errors.length) }}
        </AlertTitle>
        <AlertDescription class="text-[12px]">
          <ul class="list-disc pl-4">
            <li v-for="e in parsed.errors.slice(0, 6)" :key="e">
              {{ e }}
            </li>
          </ul>
        </AlertDescription>
      </Alert>
      <p v-else-if="clash" class="text-[12px] text-warning">
        {{ clash }}
      </p>

      <details class="text-[12px] text-muted-foreground">
        <summary class="cursor-pointer select-none hover:text-foreground">
          {{ t('themes.editor.format') }}
        </summary>
        <div class="mt-2 flex flex-col gap-1.5 leading-relaxed">
          <p><span class="font-mono text-foreground/80">base.hue</span> (0–360), <span class="font-mono text-foreground/80">base.chroma</span> (0–0.08): {{ t('themes.editor.helpBase') }}</p>
          <p><span class="font-mono text-foreground/80">accent.dark</span> / <span class="font-mono text-foreground/80">accent.light</span>: {{ t('themes.editor.helpAccent') }}</p>
          <p><span class="font-mono text-foreground/80">dark</span> / <span class="font-mono text-foreground/80">light</span>: {{ t('themes.editor.helpOverride') }} <span class="font-mono">{{ TOKENS.join(', ') }}</span>.</p>
          <p><span class="font-mono text-foreground/80">radius</span> ("0.75rem"), <span class="font-mono text-foreground/80">coverAccent</span>: {{ t('themes.editor.helpMisc') }}</p>
        </div>
      </details>

      <DialogFooter class="items-center sm:justify-between">
        <label class="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <Switch v-model="live" />
          {{ t('themes.editor.livePreview') }}
        </label>
        <Button :disabled="!parsed.theme || saving || (!!parsed.theme && themes.isBuiltin(parsed.theme.id))" @click="save">
          <Spinner v-if="saving" data-icon="inline-start" />
          {{ t('themes.editor.save') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

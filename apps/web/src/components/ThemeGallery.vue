<script setup lang="ts">
import type { ThemeDef } from '@/lib/themes'
import { CheckIcon, CopyIcon, FileDownIcon, PencilIcon, PlusIcon, Trash2Icon } from '@lucide/vue'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { toast } from 'vue-sonner'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { palette } from '@/lib/themes'
import { cn } from '@/lib/utils'
import { useThemes } from '@/stores/theme'
import ThemeEditor from './ThemeEditor.vue'

const { t } = useI18n()
const themes = useThemes()
const editorOpen = ref(false)
const editorMode = ref<'new' | 'edit' | 'import'>('new')
const editorInitial = ref<ThemeDef | null>(null)

function openEditor(mode: 'new' | 'edit' | 'import', initial: ThemeDef | null) {
  editorMode.value = mode
  editorInitial.value = initial
  editorOpen.value = true
}

function duplicate(th: ThemeDef) {
  openEditor('new', { ...JSON.parse(JSON.stringify(th)), id: `${th.id}-custom`, name: t('themes.customName', { name: themeName(th) }) })
}

async function copy(th: ThemeDef) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(th, null, 2))
    toast.success(t('themes.copied'))
  }
  catch {
    toast.error(t('themes.copyFailed'))
  }
}

async function remove(th: ThemeDef) {
  await themes.remove(th.id)
  toast.success(t('themes.removed', { name: th.name }))
}

/** Built-in themes have translated names and descriptions. */
function themeName(th: ThemeDef) {
  return themes.isBuiltin(th.id) ? t(`themes.builtin.${th.id}.name`) : th.name
}
function themeDescription(th: ThemeDef) {
  if (themes.isBuiltin(th.id))
    return t(`themes.builtin.${th.id}.description`)
  return th.description ?? (th.coverAccent !== false ? t('themes.followsCovers') : '')
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <Button size="sm" @click="duplicate(themes.current)">
        <PlusIcon data-icon="inline-start" />
        {{ t('themes.newFromCurrent') }}
      </Button>
      <Button size="sm" variant="outline" @click="openEditor('import', null)">
        <FileDownIcon data-icon="inline-start" />
        {{ t('themes.import') }}
      </Button>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <div
        v-for="th in themes.all"
        :key="th.id"
        :class="cn('group flex flex-col overflow-hidden rounded-xl bg-card ring-1 transition-shadow',
                   themes.current.id === th.id ? 'ring-2 ring-primary' : 'ring-border hover:ring-border-strong')"
      >
        <!-- Preview: a mini UI in the theme's colours (dark, then light) -->
        <button type="button" class="grid grid-cols-[3fr_2fr] text-left" :aria-label="t('themes.apply') + ' ' + themeName(th)" @click="themes.select(th)">
          <div
            v-for="(mode, i) in (['dark', 'light'] as const)"
            :key="mode"
            class="flex h-24 flex-col gap-1.5 p-2.5"
            :style="{ background: palette(th, mode).background }"
          >
            <div class="flex items-center gap-1.5">
              <span class="size-1.5 rounded-full" :style="{ background: palette(th, mode).primary }" />
              <span class="h-1 w-10 rounded-full" :style="{ background: palette(th, mode).foreground, opacity: 0.8 }" />
            </div>
            <div class="flex flex-1 flex-col justify-between rounded-md p-2" :style="{ background: palette(th, mode).card }">
              <span class="h-1 w-3/4 rounded-full" :style="{ background: palette(th, mode).mutedForeground, opacity: 0.6 }" />
              <div class="flex items-center gap-1">
                <span class="h-2.5 w-9 rounded-sm" :style="{ background: palette(th, mode).primary }" />
                <span v-if="i === 0" class="size-1.5 rounded-full" :style="{ background: palette(th, mode).success }" />
                <span v-if="i === 0" class="size-1.5 rounded-full" :style="{ background: palette(th, mode).warning }" />
              </div>
            </div>
          </div>
        </button>
        <div class="flex flex-1 flex-col gap-1 border-t px-3.5 py-3">
          <div class="flex items-center gap-2">
            <span class="text-[13.5px] font-medium">{{ themeName(th) }}</span>
            <CheckIcon v-if="themes.current.id === th.id" class="size-3.5 text-primary" />
            <span v-if="!themes.isBuiltin(th.id)" class="text-[11px] text-faint">{{ t('themes.custom') }}</span>
          </div>
          <p class="line-clamp-2 text-[12px] text-muted-foreground">
            {{ themeDescription(th) }}
          </p>
          <div class="mt-auto flex items-center gap-0.5 pt-2">
            <Tooltip>
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-xs" class="text-faint hover:text-foreground" :aria-label="t('themes.copy')" @click="copy(th)">
                  <CopyIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('themes.copy') }}</TooltipContent>
            </Tooltip>
            <Tooltip v-if="!themes.isBuiltin(th.id)">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-xs" class="text-faint hover:text-foreground" :aria-label="t('common.edit')" @click="openEditor('edit', th)">
                  <PencilIcon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('common.edit') }}</TooltipContent>
            </Tooltip>
            <Button v-else variant="ghost" size="xs" class="text-faint hover:text-foreground" @click="duplicate(th)">
              {{ t('themes.customize') }}
            </Button>
            <Tooltip v-if="!themes.isBuiltin(th.id)">
              <TooltipTrigger as-child>
                <Button variant="ghost" size="icon-xs" class="text-faint hover:text-destructive" :aria-label="t('common.delete')" @click="remove(th)">
                  <Trash2Icon />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{{ t('common.delete') }}</TooltipContent>
            </Tooltip>
            <Button
              v-if="themes.current.id !== th.id"
              variant="secondary"
              size="xs"
              class="ml-auto"
              @click="themes.select(th)"
            >
              {{ t('themes.apply') }}
            </Button>
          </div>
        </div>
      </div>
    </div>

    <ThemeEditor v-model:open="editorOpen" :initial="editorInitial" :mode="editorMode" />
  </div>
</template>

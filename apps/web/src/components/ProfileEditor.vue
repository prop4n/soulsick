<script setup lang="ts">
import type { FormatDef, QualityProfile } from '@/lib/types'
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, Trash2Icon, XIcon } from '@lucide/vue'
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import FormatTag from './FormatTag.vue'

/** Quality profile editor: accepted formats by preference, upgrade threshold. */
const props = defineProps<{ profile: Omit<QualityProfile, 'id'> & { id?: number }, formats: FormatDef[] }>()
const emit = defineEmits<{ save: [p: Omit<QualityProfile, 'id'> & { id?: number }], remove: [] }>()

const { t } = useI18n()
const draft = reactive({ ...props.profile, formats: [...props.profile.formats] })
watch(() => props.profile, p => Object.assign(draft, { ...p, formats: [...p.formats] }))

const available = computed(() => props.formats.filter(f => !draft.formats.includes(f.key)))
const dirty = computed(() => JSON.stringify({ ...draft }) !== JSON.stringify({ ...props.profile }))

function move(i: number, d: -1 | 1) {
  const j = i + d
  if (j < 0 || j >= draft.formats.length)
    return
  const f = [...draft.formats]
  ;[f[i], f[j]] = [f[j]!, f[i]!]
  draft.formats = f
}
</script>

<template>
  <div class="flex flex-col gap-5 rounded-xl bg-card p-5">
    <FieldGroup class="grid gap-4 md:grid-cols-[minmax(0,1fr)_200px_140px]">
      <Field>
        <FieldLabel class="legend">
          {{ t('profile.name') }}
        </FieldLabel>
        <Input v-model="draft.name" />
      </Field>
      <Field>
        <FieldLabel class="legend">
          {{ t('profile.upgradeUntil') }}
        </FieldLabel>
        <Select :model-value="draft.upgrade_until ?? 'none'" @update:model-value="(v) => draft.upgrade_until = v === 'none' ? null : String(v)">
          <SelectTrigger class="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="none">
                {{ t('profile.neverUpgrade') }}
              </SelectItem>
              <SelectItem v-for="f in draft.formats" :key="f" :value="f">
                {{ formats.find(x => x.key === f)?.label ?? f }}
              </SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
      <Field>
        <FieldLabel class="legend">
          {{ t('profile.maxMissing') }}
        </FieldLabel>
        <Input v-model.number="draft.max_missing_tracks" type="number" min="0" class="font-mono" />
      </Field>
    </FieldGroup>

    <div class="grid gap-5 md:grid-cols-2">
      <div class="flex flex-col gap-2">
        <span class="legend">{{ t('profile.accepted') }}</span>
        <ol class="flex flex-col rounded-md border">
          <li v-for="(f, i) in draft.formats" :key="f" class="flex items-center gap-2 border-b px-2.5 py-1.5 last:border-b-0">
            <span class="w-5 font-mono text-[11px] text-faint tnum">{{ i + 1 }}</span>
            <FormatTag :format="f" />
            <span class="flex-1 truncate text-[12.5px] text-muted-foreground">{{ formats.find(x => x.key === f)?.label }}</span>
            <Button variant="ghost" size="icon-xs" :disabled="i === 0" :aria-label="t('profile.up')" @click="move(i, -1)">
              <ArrowUpIcon />
            </Button>
            <Button variant="ghost" size="icon-xs" :disabled="i === draft.formats.length - 1" :aria-label="t('profile.down')" @click="move(i, 1)">
              <ArrowDownIcon />
            </Button>
            <Button variant="ghost" size="icon-xs" class="hover:text-destructive" :aria-label="t('common.remove')" @click="draft.formats = draft.formats.filter(x => x !== f)">
              <XIcon />
            </Button>
          </li>
          <li v-if="!draft.formats.length" class="px-3 py-3 text-[12px] text-destructive">
            {{ t('profile.noneAccepted') }}
          </li>
        </ol>
      </div>
      <div class="flex flex-col gap-2">
        <span class="legend">{{ t('profile.refused') }}</span>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="f in available"
            :key="f.key"
            type="button"
            class="inline-flex h-7 items-center gap-1 rounded-lg bg-card/50 px-2 text-[12px] text-muted-foreground transition-colors hover:border-solid hover:text-foreground"
            @click="draft.formats = [...draft.formats, f.key]"
          >
            <PlusIcon class="size-3" />
            {{ f.label }}
          </button>
        </div>
        <FieldDescription class="mt-1 text-[12px]">
          {{ t('profile.refusedHint') }}
        </FieldDescription>
      </div>
    </div>

    <div class="flex items-center justify-between">
      <Button v-if="profile.id" variant="ghost" size="sm" class="text-faint hover:text-destructive" @click="emit('remove')">
        <Trash2Icon data-icon="inline-start" />
        {{ t('common.delete') }}
      </Button>
      <span v-else />
      <Button size="sm" :disabled="!dirty && !!profile.id" @click="emit('save', { ...draft, formats: [...draft.formats] })">
        {{ profile.id ? t('common.save') : t('profile.create') }}
      </Button>
    </div>
  </div>
</template>

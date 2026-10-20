<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useSession } from '@/stores/session'

const { t } = useI18n()
const session = useSession()
const router = useRouter()
const route = useRoute()

const setup = computed(() => session.state?.setup_required ?? false)
const username = ref('admin')
const password = ref('')
const error = ref<string | null>(null)
const busy = ref(false)

async function submit() {
  error.value = null
  busy.value = true
  try {
    await session.login(username.value, password.value, setup.value)
    router.replace((route.query.next as string) || { name: 'home' })
  }
  catch (e) {
    error.value = (e as Error).message
  }
  finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="grid min-h-svh place-items-center bg-background px-4">
    <div class="flex w-full max-w-[360px] flex-col gap-8">
      <div class="flex flex-col items-center gap-3 text-center">
        <div class="flex items-baseline gap-2">
          <span class="font-serif text-[44px] leading-none italic tracking-tight">soulsick</span>
          <span class="size-2 rounded-full bg-primary shadow-[0_0_10px_var(--primary)]" />
        </div>
        <p class="text-[13px] text-muted-foreground text-balance">
          {{ setup
            ? t('login.setupHint')
            : t('login.tagline') }}
        </p>
      </div>

      <form class="flex flex-col gap-5 rounded-xl bg-card p-6" @submit.prevent="submit">
        <FieldGroup>
          <Field>
            <FieldLabel for="u">
              {{ t('common.username') }}
            </FieldLabel>
            <Input id="u" v-model="username" autocomplete="username" required />
          </Field>
          <Field :data-invalid="!!error || undefined">
            <FieldLabel for="p">
              {{ t('common.password') }}
            </FieldLabel>
            <Input
              id="p"
              v-model="password"
              type="password"
              :autocomplete="setup ? 'new-password' : 'current-password'"
              :minlength="8"
              required
              :aria-invalid="!!error || undefined"
            />
            <FieldDescription v-if="setup">
              {{ t('login.passwordHint') }}
            </FieldDescription>
          </Field>
        </FieldGroup>
        <Alert v-if="error" variant="destructive">
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>
        <Button type="submit" :disabled="busy">
          <Spinner v-if="busy" data-icon="inline-start" />
          {{ setup ? t('login.create') : t('login.submit') }}
        </Button>
      </form>
    </div>
  </div>
</template>

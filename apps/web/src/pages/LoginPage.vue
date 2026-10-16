<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useSession } from '@/stores/session'

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
        <span class="wordmark rounded-[4px] bg-primary px-3 py-2 text-[26px] leading-none text-primary-foreground">soulsick</span>
        <p class="text-[13px] text-muted-foreground text-balance">
          {{ setup
            ? 'Première mise en route : crée le compte qui protégera cette instance.'
            : 'Client Soulseek et bibliothèque, sans boîte noire.' }}
        </p>
      </div>

      <form class="flex flex-col gap-5 rounded-lg border bg-card p-6" @submit.prevent="submit">
        <FieldGroup>
          <Field>
            <FieldLabel for="u">
              Identifiant
            </FieldLabel>
            <Input id="u" v-model="username" autocomplete="username" required />
          </Field>
          <Field :data-invalid="!!error || undefined">
            <FieldLabel for="p">
              Mot de passe
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
              8 caractères minimum. Stocké sous forme de hash scrypt dans /config.
            </FieldDescription>
          </Field>
        </FieldGroup>
        <Alert v-if="error" variant="destructive">
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>
        <Button type="submit" :disabled="busy">
          <Spinner v-if="busy" data-icon="inline-start" />
          {{ setup ? 'Créer le compte' : 'Entrer' }}
        </Button>
      </form>
    </div>
  </div>
</template>

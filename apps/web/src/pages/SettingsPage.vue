<script setup lang="ts">
import type { AppSettings, QualityProfile } from '@/lib/types'
import { PlusIcon } from '@lucide/vue'
import { useMutation, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import PageHeader from '@/components/PageHeader.vue'
import ProfileEditor from '@/components/ProfileEditor.vue'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSeparator, FieldSet, FieldLegend } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Spinner } from '@/components/ui/spinner'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useFormats, useProfiles, useSettings, useStatus } from '@/composables/queries'
import { api } from '@/lib/api'

const qc = useQueryClient()
const { data: settings, isPending } = useSettings()
const { data: profiles } = useProfiles()
const { data: formats } = useFormats()
const { data: status } = useStatus()

const tab = ref('soulseek')
const form = ref<AppSettings | null>(null)
watch(settings, (s) => {
  if (s)
    form.value = JSON.parse(JSON.stringify(s))
}, { immediate: true })
const dirty = computed(() => !!form.value && JSON.stringify(form.value) !== JSON.stringify(settings.value))

const save = useMutation({
  mutationFn: () => api.put<AppSettings>('/settings', form.value),
  onSuccess: (s) => {
    qc.setQueryData(['settings'], s)
    form.value = JSON.parse(JSON.stringify(s))
    toast.success('Réglages enregistrés', { description: 'Le changement est tracé dans le journal.' })
  },
  onError: e => toast.error(e.message),
})
const testNavidrome = useMutation({
  mutationFn: () => api.post<{ ok: boolean, error?: string }>('/settings/navidrome/test'),
  onSuccess: r => (r.ok ? toast.success('Navidrome a accepté le scan') : toast.error('Navidrome', { description: r.error })),
})

// Aperçu du modèle de nommage, calculé comme côté serveur
const sample = { albumartist: 'Nirvana', artist: 'Nirvana', album: 'Nevermind', year: '1991', title: 'In Bloom', track: 2, disc: 1 }
const namingPreview = computed(() => {
  const tpl = form.value?.library.naming_template ?? ''
  const render = (discCount: number) => `${tpl
    .replace(/\{(\w+)(?::0?(\d+))?\}/g, (_, k: string, pad?: string) => {
      if (k === 'disc_prefix')
        return discCount > 1 ? `${sample.disc}-` : ''
      const v = (sample as Record<string, string | number>)[k]
      if (v === undefined)
        return ''
      return pad ? String(v).padStart(Number(pad), '0') : String(v)
    })
    .split('/')
    .map(s => s.trim())
    .filter(Boolean)
    .join('/')}.flac`
  return [render(1), render(2)]
})

// Profils
const newProfile = ref<Omit<QualityProfile, 'id'> | null>(null)
const saveProfile = useMutation({
  mutationFn: (p: Omit<QualityProfile, 'id'> & { id?: number }) =>
    p.id ? api.put(`/profiles/${p.id}`, p) : api.post('/profiles', p),
  onSuccess: () => {
    newProfile.value = null
    toast.success('Profil enregistré')
    qc.invalidateQueries({ queryKey: ['profiles'] })
  },
  onError: e => toast.error(e.message),
})
const removeProfile = useMutation({
  mutationFn: (id: number) => api.del(`/profiles/${id}`),
  onSuccess: () => qc.invalidateQueries({ queryKey: ['profiles'] }),
  onError: e => toast.error(e.message),
})
</script>

<template>
  <div class="flex flex-col">
    <PageHeader eyebrow="Système" title="Réglages" description="Chaque modification est enregistrée dans le journal.">
      <template #actions>
        <Button v-if="tab !== 'profiles'" size="sm" :disabled="!dirty || save.isPending.value" @click="save.mutate()">
          <Spinner v-if="save.isPending.value" data-icon="inline-start" />
          Enregistrer
        </Button>
      </template>
    </PageHeader>

    <div v-if="isPending || !form" class="flex flex-col gap-3">
      <Skeleton v-for="i in 4" :key="i" class="h-12 w-full max-w-2xl" />
    </div>

    <Tabs v-else v-model="tab" class="gap-6">
      <TabsList class="flex-wrap">
        <TabsTrigger value="soulseek">
          Soulseek
        </TabsTrigger>
        <TabsTrigger value="hunter">
          Chasse
        </TabsTrigger>
        <TabsTrigger value="library">
          Bibliothèque
        </TabsTrigger>
        <TabsTrigger value="profiles">
          Profils qualité
        </TabsTrigger>
        <TabsTrigger value="navidrome">
          Navidrome
        </TabsTrigger>
      </TabsList>

      <TabsContent value="soulseek" class="max-w-2xl">
        <FieldGroup>
          <FieldSet>
            <FieldLegend>Compte</FieldLegend>
            <FieldDescription>Le compte est créé automatiquement par le serveur à la première connexion s’il n’existe pas.</FieldDescription>
            <div class="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel for="su">
                  Utilisateur
                </FieldLabel>
                <Input id="su" v-model="form.soulseek.username" class="font-mono" autocomplete="off" />
              </Field>
              <Field>
                <FieldLabel for="sp">
                  Mot de passe
                </FieldLabel>
                <Input id="sp" v-model="form.soulseek.password" type="password" autocomplete="new-password" />
              </Field>
            </div>
            <Field>
              <FieldLabel for="sd">
                Description publique
              </FieldLabel>
              <Input id="sd" v-model="form.soulseek.description" />
            </Field>
          </FieldSet>
          <FieldSeparator />
          <FieldSet>
            <FieldLegend>Réseau</FieldLegend>
            <div class="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel for="lp">
                  Port d’écoute
                </FieldLabel>
                <Input id="lp" v-model.number="form.soulseek.listen_port" type="number" class="font-mono" />
                <FieldDescription>À ouvrir/rediriger (et le suivant, {{ form.soulseek.listen_port + 1 }}, pour l’obfuscation).</FieldDescription>
              </Field>
              <Field orientation="horizontal" class="self-start pt-7">
                <Switch id="upnp" v-model="form.soulseek.upnp" />
                <FieldLabel for="upnp">
                  UPnP (ouverture automatique du port)
                </FieldLabel>
              </Field>
            </div>
          </FieldSet>
          <FieldSeparator />
          <FieldSet>
            <FieldLegend>Partage</FieldLegend>
            <div class="grid gap-4 sm:grid-cols-3">
              <Field>
                <FieldLabel for="slots">
                  Slots d’envoi
                </FieldLabel>
                <Input id="slots" v-model.number="form.soulseek.upload_slots" type="number" min="0" class="font-mono" />
              </Field>
              <Field>
                <FieldLabel for="ul">
                  Limite envoi (Ko/s)
                </FieldLabel>
                <Input id="ul" v-model.number="form.soulseek.upload_speed_kbps" type="number" min="0" class="font-mono" />
                <FieldDescription>0 = illimité</FieldDescription>
              </Field>
              <Field>
                <FieldLabel for="dl">
                  Limite réception (Ko/s)
                </FieldLabel>
                <Input id="dl" v-model.number="form.soulseek.download_speed_kbps" type="number" min="0" class="font-mono" />
                <FieldDescription>0 = illimité</FieldDescription>
              </Field>
            </div>
            <Field orientation="horizontal">
              <Switch id="sl" v-model="form.soulseek.share_library" />
              <FieldLabel for="sl">
                Partager la bibliothèque ({{ status?.paths.music }})
              </FieldLabel>
            </Field>
          </FieldSet>
          <p class="text-[12px] text-faint">
            Modifier le compte ou le réseau reconnecte le moteur Soulseek.
          </p>
        </FieldGroup>
      </TabsContent>

      <TabsContent value="hunter" class="max-w-2xl">
        <FieldGroup>
          <Field orientation="horizontal">
            <Switch id="he" v-model="form.hunter.enabled" />
            <FieldLabel for="he">
              Chasse automatique des albums recherchés
            </FieldLabel>
          </Field>
          <div class="grid gap-4 sm:grid-cols-3">
            <Field>
              <FieldLabel for="hi">
                Intervalle (min)
              </FieldLabel>
              <Input id="hi" v-model.number="form.hunter.interval_minutes" type="number" min="5" class="font-mono" />
            </Field>
            <Field>
              <FieldLabel for="hm">
                Albums par passage
              </FieldLabel>
              <Input id="hm" v-model.number="form.hunter.max_searches_per_run" type="number" min="1" class="font-mono" />
              <FieldDescription>Reste raisonnable : le réseau limite les recherches.</FieldDescription>
            </Field>
            <Field>
              <FieldLabel for="hw">
                Écoute par requête (s)
              </FieldLabel>
              <Input id="hw" v-model.number="form.hunter.search_wait_seconds" type="number" min="5" class="font-mono" />
            </Field>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel for="hp">
                Propositions en mode validation
              </FieldLabel>
              <Input id="hp" v-model.number="form.hunter.proposals" type="number" min="1" class="font-mono" />
            </Field>
            <Field>
              <FieldLabel for="hmm">
                Correspondance minimale des titres
              </FieldLabel>
              <Input id="hmm" v-model.number="form.hunter.min_match" type="number" min="0" max="1" step="0.05" class="font-mono" />
              <FieldDescription>0,6 = 60 % de ressemblance moyenne avec la tracklist MusicBrainz.</FieldDescription>
            </Field>
          </div>
          <Field orientation="horizontal">
            <Switch id="hc" v-model="form.hunter.download_covers" />
            <FieldLabel for="hc">
              Télécharger aussi pochettes, .cue et .log du dossier
            </FieldLabel>
          </Field>
        </FieldGroup>
      </TabsContent>

      <TabsContent value="library" class="max-w-2xl">
        <FieldGroup>
          <Field>
            <FieldLabel for="nt">
              Modèle de rangement
            </FieldLabel>
            <Input id="nt" v-model="form.library.naming_template" class="font-mono" />
            <FieldDescription>
              Variables : <code class="font-mono">{albumartist} {artist} {album} {year} {title} {track:02} {disc} {disc_prefix} {release_type}</code>
            </FieldDescription>
            <div class="mt-1 flex flex-col gap-1 rounded-md bg-well px-3 py-2.5 font-mono text-[12px] ring-1 ring-border ring-inset">
              <span><span class="text-faint">{{ status?.paths.music }}/</span>{{ namingPreview[0] }}</span>
              <span class="text-muted-foreground"><span class="text-faint">multi-disques : …/</span>{{ namingPreview[1].split('/').pop() }}</span>
            </div>
          </Field>
          <div class="grid gap-4 sm:grid-cols-2">
            <Field orientation="horizontal">
              <Switch id="wt" v-model="form.library.write_tags" />
              <FieldLabel for="wt">
                Écrire les tags MusicBrainz
              </FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <Switch id="ec" v-model="form.library.embed_cover" />
              <FieldLabel for="ec">
                Intégrer la pochette aux fichiers
              </FieldLabel>
            </Field>
          </div>
          <Field class="sm:max-w-xs">
            <FieldLabel for="si">
              Resynchroniser MusicBrainz toutes les (h)
            </FieldLabel>
            <Input id="si" v-model.number="form.library.sync_interval_hours" type="number" min="1" class="font-mono" />
          </Field>
          <FieldSeparator />
          <dl class="grid gap-2 text-[12.5px]">
            <div class="flex gap-3">
              <dt class="w-28 shrink-0 text-faint">
                Bibliothèque
              </dt><dd class="font-mono">
                {{ status?.paths.music }}
              </dd>
            </div>
            <div class="flex gap-3">
              <dt class="w-28 shrink-0 text-faint">
                Réception
              </dt><dd class="font-mono">
                {{ status?.paths.downloads }}
              </dd>
            </div>
            <div class="flex gap-3">
              <dt class="w-28 shrink-0 text-faint">
                Configuration
              </dt><dd class="font-mono">
                {{ status?.paths.config }}
              </dd>
            </div>
          </dl>
          <p class="text-[12px] text-faint">
            Les chemins se règlent par variables d’environnement / volumes Docker.
          </p>
        </FieldGroup>
      </TabsContent>

      <TabsContent value="profiles" class="flex flex-col gap-4">
        <p class="max-w-2xl text-[12.5px] text-muted-foreground">
          Un profil dit quels formats Soulsick a le droit de télécharger, dans quel ordre de préférence, et jusqu’où il doit chercher à améliorer un album déjà présent.
        </p>
        <ProfileEditor
          v-for="p in profiles ?? []"
          :key="p.id"
          :profile="p"
          :formats="formats ?? []"
          @save="(v) => saveProfile.mutate(v)"
          @remove="removeProfile.mutate(p.id)"
        />
        <ProfileEditor
          v-if="newProfile"
          :profile="newProfile"
          :formats="formats ?? []"
          @save="(v) => saveProfile.mutate(v)"
        />
        <Button v-else variant="outline" size="sm" class="w-fit" @click="newProfile = { name: 'Nouveau profil', formats: ['flac', 'mp3-320'], upgrade_until: null, max_missing_tracks: 0 }">
          <PlusIcon data-icon="inline-start" />
          Nouveau profil
        </Button>
      </TabsContent>

      <TabsContent value="navidrome" class="max-w-2xl">
        <FieldGroup>
          <FieldDescription>
            Monte le même dossier de bibliothèque dans Navidrome (en lecture seule). Optionnellement, Soulsick lui demande un scan après chaque import.
          </FieldDescription>
          <Field orientation="horizontal">
            <Switch id="ne" v-model="form.navidrome.enabled" />
            <FieldLabel for="ne">
              Déclencher un scan après import
            </FieldLabel>
          </Field>
          <Field>
            <FieldLabel for="nu">
              URL
            </FieldLabel>
            <Input id="nu" v-model="form!.navidrome.url" placeholder="http://navidrome:4533" class="font-mono" />
          </Field>
          <div class="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel for="nn">
                Utilisateur
              </FieldLabel>
              <Input id="nn" v-model="form!.navidrome.username" autocomplete="off" />
            </Field>
            <Field>
              <FieldLabel for="np">
                Mot de passe
              </FieldLabel>
              <Input id="np" v-model="form!.navidrome.password" type="password" autocomplete="new-password" />
            </Field>
          </div>
          <Button variant="outline" size="sm" class="w-fit" :disabled="dirty || testNavidrome.isPending.value" @click="testNavidrome.mutate()">
            Tester (scan maintenant)
          </Button>
          <FieldDescription v-if="dirty">
            Enregistre avant de tester.
          </FieldDescription>
        </FieldGroup>
      </TabsContent>
    </Tabs>
  </div>
</template>

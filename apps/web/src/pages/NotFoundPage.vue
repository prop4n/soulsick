<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { Button } from '@/components/ui/button'

const { t } = useI18n()
const route = useRoute()
</script>

<template>
  <div class="flex max-w-md flex-col gap-4 py-16">
    <p class="font-serif text-[64px] leading-none italic text-faint">
      404
    </p>
    <h1 class="text-[22px] font-semibold tracking-[-0.015em]">
      {{ t('notFound.title') }}
    </h1>
    <p class="text-[13.5px] text-muted-foreground">
      {{ t('notFound.body') }} <span class="font-mono text-foreground/80">{{ route.fullPath }}</span>
    </p>
    <div class="flex gap-2">
      <Button size="sm" as-child>
        <RouterLink :to="{ name: 'home' }">
          {{ t('notFound.home') }}
        </RouterLink>
      </Button>
      <Button size="sm" variant="ghost" @click="$router.back()">
        {{ t('notFound.back') }}
      </Button>
    </div>
  </div>
</template>

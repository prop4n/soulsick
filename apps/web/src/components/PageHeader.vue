<script setup lang="ts">
defineProps<{ title: string, description?: string }>()
</script>

<template>
  <header class="flex flex-col gap-4 pb-6 sm:flex-row sm:items-end sm:justify-between">
    <div class="flex min-w-0 flex-col gap-1.5">
      <h1 class="text-[26px] leading-tight font-semibold tracking-[-0.02em] text-foreground text-balance">
        {{ title }}
      </h1>
      <p v-if="description" class="max-w-2xl text-[13.5px] text-muted-foreground text-pretty">
        {{ description }}
      </p>
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="flex shrink-0 flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>

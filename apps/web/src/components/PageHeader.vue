<script setup lang="ts">
defineProps<{ eyebrow?: string, title: string, description?: string }>()
</script>

<template>
  <header class="flex flex-col gap-4 pb-6 sm:flex-row sm:items-end sm:justify-between">
    <div class="flex min-w-0 flex-col gap-1.5">
      <p v-if="eyebrow" class="legend">
        {{ eyebrow }}
      </p>
      <h1 class="spine text-[34px] text-foreground text-balance sm:text-[40px]">
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

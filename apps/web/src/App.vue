<script setup lang="ts">
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import 'vue-sonner/style.css'
</script>

<template>
  <TooltipProvider :delay-duration="250">
    <RouterView />
  </TooltipProvider>
  <Toaster position="bottom-right" :theme="'system'" />
</template>

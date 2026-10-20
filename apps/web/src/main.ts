import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { i18n } from './i18n'
import { setUnauthorizedHandler } from './lib/api'
import { applyTheme, followSystemTheme } from './lib/theme'
import { router } from './router'
import { useSession } from './stores/session'
import { bootTheme } from './stores/theme'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/instrument-serif/400.css'
import '@fontsource/instrument-serif/400-italic.css'
import './style.css'

applyTheme()
followSystemTheme()
bootTheme()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: 1 },
  },
})

const app = createApp(App)
const pinia = createPinia()
app.use(i18n)
app.use(pinia)
app.use(router)
app.use(VueQueryPlugin, { queryClient })

setUnauthorizedHandler(async () => {
  const session = useSession(pinia)
  await session.refresh()
  if (router.currentRoute.value.name !== 'login')
    router.push({ name: 'login' })
})

app.mount('#app')

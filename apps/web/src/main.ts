import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { setUnauthorizedHandler } from './lib/api'
import { router } from './router'
import { useSession } from './stores/session'
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource-variable/martian-mono/wdth.css'
import './style.css'

const theme = localStorage.getItem('soulsick-theme') ?? 'dark'
document.documentElement.classList.toggle('dark', theme === 'dark')

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: 1 },
  },
})

const app = createApp(App)
const pinia = createPinia()
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

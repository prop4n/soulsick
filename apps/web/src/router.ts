import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '@/stores/session'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/connexion', name: 'login', component: () => import('@/pages/LoginPage.vue'), meta: { public: true } },
    {
      path: '/',
      component: () => import('@/layouts/AppShell.vue'),
      children: [
        { path: '', name: 'home', component: () => import('@/pages/DashboardPage.vue'), meta: { title: 'Console' } },
        { path: 'artistes', name: 'artists', component: () => import('@/pages/ArtistsPage.vue'), meta: { title: 'Artistes' } },
        { path: 'artistes/:id', name: 'artist', component: () => import('@/pages/ArtistPage.vue'), meta: { title: 'Artiste' } },
        { path: 'albums/:id', name: 'album', component: () => import('@/pages/AlbumPage.vue'), meta: { title: 'Album' } },
        { path: 'file', name: 'queue', component: () => import('@/pages/QueuePage.vue'), meta: { title: 'File' } },
        { path: 'recherche', name: 'search', component: () => import('@/pages/SearchPage.vue'), meta: { title: 'Recherche' } },
        { path: 'transferts', name: 'transfers', component: () => import('@/pages/TransfersPage.vue'), meta: { title: 'Transferts' } },
        { path: 'pairs/:username?', name: 'browse', component: () => import('@/pages/BrowsePage.vue'), meta: { title: 'Parcourir' } },
        { path: 'partages', name: 'shares', component: () => import('@/pages/SharesPage.vue'), meta: { title: 'Partages' } },
        { path: 'logs', name: 'logs', component: () => import('@/pages/LogsPage.vue'), meta: { title: 'Logs' } },
        { path: 'journal', name: 'journal', component: () => import('@/pages/JournalPage.vue'), meta: { title: 'Journal' } },
        { path: 'reglages', name: 'settings', component: () => import('@/pages/SettingsPage.vue'), meta: { title: 'Réglages' } },
      ],
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const session = useSession()
  const st = session.state ?? await session.refresh()
  if (!to.meta.public && !st.authenticated)
    return { name: 'login', query: to.fullPath !== '/' ? { next: to.fullPath } : undefined }
  if (to.name === 'login' && st.authenticated)
    return { name: 'home' }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Soulsick` : 'Soulsick'
})

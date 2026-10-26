import { createRouter, createWebHistory } from 'vue-router'
import { t } from '@/i18n'
import { useSession } from '@/stores/session'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/pages/LoginPage.vue'), meta: { public: true, title: 'nav.login' } },
    {
      path: '/',
      component: () => import('@/layouts/AppShell.vue'),
      children: [
        { path: '', name: 'home', component: () => import('@/pages/HomePage.vue'), meta: { title: 'nav.home' } },
        { path: 'artists', name: 'artists', component: () => import('@/pages/ArtistsPage.vue'), meta: { title: 'nav.artists' } },
        { path: 'artists/:id', name: 'artist', component: () => import('@/pages/ArtistPage.vue'), meta: { title: 'nav.artist' } },
        { path: 'albums/:id', name: 'album', component: () => import('@/pages/AlbumPage.vue'), meta: { title: 'nav.album' } },
        { path: 'library', name: 'library', component: () => import('@/pages/LibraryPage.vue'), meta: { title: 'nav.library' } },
        { path: 'discover', name: 'discover', component: () => import('@/pages/DiscoverPage.vue'), meta: { title: 'nav.discover' } },
        { path: 'search', name: 'search', component: () => import('@/pages/SearchPage.vue'), meta: { title: 'nav.search' } },
        { path: 'transfers', name: 'transfers', component: () => import('@/pages/TransfersPage.vue'), meta: { title: 'nav.transfers' } },
        { path: 'browse/:username?', name: 'browse', component: () => import('@/pages/BrowsePage.vue'), meta: { title: 'nav.browse' } },
        { path: 'peers/:username', name: 'peer', component: () => import('@/pages/PeerPage.vue'), meta: { title: 'nav.peer' } },
        { path: 'chat', name: 'chat', component: () => import('@/pages/ChatPage.vue'), meta: { title: 'nav.chat' } },
        { path: 'shares', name: 'shares', component: () => import('@/pages/SharesPage.vue'), meta: { title: 'nav.shares' } },
        { path: 'activity', name: 'activity', component: () => import('@/pages/ActivityPage.vue'), meta: { title: 'nav.activity' } },
        { path: 'settings', name: 'settings', component: () => import('@/pages/SettingsPage.vue'), meta: { title: 'nav.settings' } },
        // Old (French) paths
        { path: 'artistes/:id?', redirect: to => (to.params.id ? { name: 'artist', params: { id: to.params.id } } : { name: 'artists' }) },
        { path: 'bibliotheque', redirect: { name: 'library' } },
        { path: 'existant', redirect: { name: 'library', query: { tab: 'import' } } },
        { path: 'file', redirect: { name: 'home' } },
        { path: 'recherche', redirect: to => ({ name: 'search', query: to.query }) },
        { path: 'transferts', redirect: { name: 'transfers' } },
        { path: 'pairs/:username?', redirect: to => (to.params.username ? { name: 'peer', params: to.params } : { name: 'browse' }) },
        { path: 'partages', redirect: { name: 'shares' } },
        { path: 'journal', redirect: { name: 'activity' } },
        { path: 'logs', redirect: { name: 'activity', query: { tab: 'logs' } } },
        { path: 'reglages', redirect: to => ({ name: 'settings', query: to.query }) },
        { path: ':pathMatch(.*)*', name: 'not-found', component: () => import('@/pages/NotFoundPage.vue'), meta: { title: 'nav.notFound' } },
      ],
    },
    { path: '/connexion', redirect: to => ({ name: 'login', query: to.query }) },
  ],
  scrollBehavior: (to, from) => (to.name === from.name ? undefined : { top: 0 }),
})

router.beforeEach(async (to) => {
  const session = useSession()
  const st = session.state ?? await session.refresh()
  if (!to.meta.public && !st.authenticated)
    return { name: 'login', query: to.fullPath !== '/' ? { next: to.fullPath } : undefined }
  if (to.name === 'login' && st.authenticated)
    return { name: 'home' }
})

export function pageTitle(): string {
  const key = router.currentRoute.value.meta.title as string | undefined
  return key ? `${t(key)} · Soulsick` : 'Soulsick'
}

router.afterEach(() => {
  document.title = pageTitle()
})

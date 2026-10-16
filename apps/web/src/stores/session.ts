import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/lib/api'

interface AuthState { setup_required: boolean, authenticated: boolean, username: string | null }

export const useSession = defineStore('session', () => {
  const state = ref<AuthState | null>(null)

  async function refresh() {
    state.value = await api.get<AuthState>('/auth/state')
    return state.value
  }

  async function login(username: string, password: string, setup: boolean) {
    await api.post(setup ? '/auth/setup' : '/auth/login', { username, password })
    await refresh()
  }

  async function logout() {
    await api.post('/auth/logout')
    await refresh()
  }

  return { state, refresh, login, logout }
})

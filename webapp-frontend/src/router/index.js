import { createRouter, createWebHistory } from 'vue-router'
import UserInfo from '../views/UserInfo.vue'
import Rankings from '../views/Rankings.vue'

const routes = [
  {
    path: '/',
    redirect: '/user-info'
  },
  {
    path: '/user-info',
    name: 'user-info',
    component: UserInfo
  },
  {
    path: '/rankings',
    name: 'rankings',
    component: Rankings
  }
]

const router = createRouter({
  history: createWebHistory(process.env.BASE_URL),
  routes
})

export default router

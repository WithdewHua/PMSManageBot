import { createRouter, createWebHashHistory } from 'vue-router'
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
  history: createWebHashHistory(process.env.BASE_URL),
  routes
})

// 确保初始化时路由正确
router.beforeEach((to, from, next) => {
  if (to.path === '/' && to.hash === '') {
    next({ path: '/user-info' });
  } else {
    next();
  }
});

export default router

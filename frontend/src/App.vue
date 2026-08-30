<script setup lang="ts">
import { ACCESS_KEY } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
if (localStorage.getItem(ACCESS_KEY)) {
  auth.fetchMe().catch(() => undefined)
}
</script>

<template>
  <router-view />
</template>

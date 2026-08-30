<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const auth = useAuthStore()
const form = ref({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    await auth.doLogin(form.value.username, form.value.password)
    router.push('/')
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <el-card class="login-card" shadow="always">
      <template #header>
        <h2 class="login-title">智能编程教学辅助系统</h2>
      </template>
      <el-form @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" class="login-submit" :loading="loading" @click="submit">
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--color-background);
}

.login-card {
  width: 380px;
  border-radius: 16px;
}

.login-title {
  font-size: 18px;
  text-align: center;
  color: var(--color-foreground);
}

.login-submit {
  width: 100%;
  border-radius: 8px;
}
</style>

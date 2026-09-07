import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'happy-dom',
    // e2e 由 Playwright 跑（tests/e2e/），不能进 vitest
    exclude: ['**/node_modules/**', '**/dist/**', 'tests/e2e/**'],
  },
})

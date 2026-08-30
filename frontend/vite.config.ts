import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    // Element Plus 全量引入约 938 kB（gzip 302 kB），已单独分包。
    // 演示原型不引入按需导入插件以避免额外构建复杂度，故上调告警阈值。
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // Element Plus 全量约 1MB，与框架/业务分离以便长期缓存
        manualChunks: {
          vue: ['vue', 'vue-router', 'pinia'],
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
        },
      },
    },
  },
})

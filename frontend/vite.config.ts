import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  // NO_TW=1 用于「重采无 Tailwind 旧版基线」的回归脚本；常规开发与构建请保持开启。
  plugins: process.env.NO_TW ? [vue()] : [vue(), tailwindcss()],
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
          // Markdown 渲染（markdown-it + DOMPurify + highlight.js）单独分包，
          // 内容不常变，可与视图代码分开缓存
          markdown: ['markdown-it', 'dompurify', 'highlight.js'],
          // Monaco 只在 /editor 路由被访问时下载（CodeEditor.vue 内再做动态 import），
          // 单独成块以便长期缓存，也避免它挤进业务包
          monaco: ['monaco-editor'],
        },
      },
    },
  },
})

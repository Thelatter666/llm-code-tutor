import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// highlight.js 主题只提供 token 配色；代码块底色 / 圆角由 MarkdownView 的
// scoped 样式按 ui-baseline 变量统一控制
import 'highlight.js/styles/github.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './styles/theme.css'

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')

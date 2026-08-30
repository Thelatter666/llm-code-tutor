/**
 * AI 回答的 Markdown 渲染 + XSS 消毒（双层）。
 *
 * 1. `html: false`：markdown-it 把源里的原生 HTML 一律转义成文本 —— AI 输出
 *    不可信，第一层就不给它执行 HTML 的机会；
 * 2. `DOMPurify.sanitize`：渲染产物再消毒一次兜底 —— 即使上游配置被改错，
 *    脚本类载荷也进不了 DOM。
 *
 * `MarkdownView.vue` 是 v-html 的唯一豁免点，且只允许渲染本函数的产物。
 * 高亮按需注册语言（python / javascript / typescript / json / bash），
 * 控制highlight.js 的打包体积；未知语言回退为转义文本。
 */
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import MarkdownIt from 'markdown-it'

hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)

const md: InstanceType<typeof MarkdownIt> = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    const body =
      lang && hljs.getLanguage(lang)
        ? hljs.highlight(code, { language: lang }).value
        : md.utils.escapeHtml(code)
    return `<pre class="hljs"><code>${body}</code></pre>`
  },
})

export function renderMarkdown(source: string): string {
  return DOMPurify.sanitize(md.render(source))
}

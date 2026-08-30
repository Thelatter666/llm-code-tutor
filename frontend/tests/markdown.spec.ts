import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/utils/markdown'

/**
 * XSS 消毒策略的自动化测试（P3 并入任务 2）。
 *
 * 策略是双层的：
 * 1. markdown-it `html: false` —— 源里的原生 HTML 一律转义为文本；
 * 2. DOMPurify.sanitize —— 渲染产物再消毒一次兜底。
 * AI 输出不可信，任何一层单独失效都不能让脚本类载荷进入 DOM。
 */
describe('renderMarkdown 消毒策略', () => {
  it('渲染基本 Markdown 结构', () => {
    const html = renderMarkdown('**粗体** 与 `code`')
    expect(html).toContain('<strong>粗体</strong>')
    expect(html).toContain('<code>code</code>')
  })

  it('原生 <script> 被转义为文本而非执行', () => {
    const html = renderMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('alert(1)</script>')
  })

  it('内联事件处理器不进入活 HTML（整段被转义为可见文本）', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>')
    // html:false 把整段转义成 &lt;img …&gt; 文本 —— 无活标签即可执行面为零
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })

  it('javascript: 链接不成活链接（markdown-it 校验拒绝，DOMPurify 兜底）', () => {
    const html = renderMarkdown('[点我](javascript:alert(1))')
    expect(html).not.toContain('<a ')
    expect(html).not.toContain('href')
  })

  it('iframe / object 等危险标签不进入产物', () => {
    const html = renderMarkdown('<iframe src="https://evil.example"></iframe>')
    expect(html).not.toContain('<iframe')
  })

  it('代码围栏有语法高亮 class', () => {
    const html = renderMarkdown('```python\nprint("hi")\n```')
    expect(html).toContain('hljs')
  })

  it('未知语言的围栏回退为转义文本，不炸', () => {
    const html = renderMarkdown('```brainfuck\n+[----]\n```')
    expect(html).toContain('+[----]')
  })

  it('空串与纯文本不炸', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown('普通一行文字')).toContain('普通一行文字')
  })
})

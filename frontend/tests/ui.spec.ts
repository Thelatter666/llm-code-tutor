/**
 * ui/ 适配层最小用例（spec §5 / Plan Task 4）。
 * 仅断言渲染与 class 拼接，组件无业务逻辑。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { cn } from '@/lib/utils'
import UiBadge from '@/ui/UiBadge.vue'
import UiButton from '@/ui/UiButton.vue'
import UiCard from '@/ui/UiCard.vue'
import UiAlert from '@/ui/UiAlert.vue'
import UiEmpty from '@/ui/UiEmpty.vue'
import UiTextarea from '@/ui/UiTextarea.vue'
import UiIcon from '@/ui/UiIcon.vue'

describe('cn()', () => {
  it('合并并去重冲突类名', () => {
    expect(cn('p-2', 'p-4')).toBe('p-4')
    expect(cn('foo', false && 'bar', 'baz')).toBe('foo baz')
  })
})

describe('UiButton', () => {
  it('默认 variant/size 输出正确类名', () => {
    const w = mount(UiButton, { slots: { default: 'Go' } })
    expect(w.classes()).toContain('bg-brand')
    expect(w.classes()).toContain('h-9')
    expect(w.text()).toBe('Go')
  })
  it('variant=ghost 不带 brand 背景', () => {
    const w = mount(UiButton, { props: { variant: 'ghost' } })
    expect(w.classes()).not.toContain('bg-brand')
    expect(w.classes()).toContain('hover:bg-softer')
  })
  it('size=icon 渲染方形', () => {
    const w = mount(UiButton, { props: { size: 'icon' }, slots: { default: 'X' } })
    expect(w.classes()).toContain('h-9')
    expect(w.classes()).toContain('w-9')
  })
})

describe('UiBadge', () => {
  it('默认 variant=muted', () => {
    const w = mount(UiBadge, { slots: { default: '管理员' } })
    expect(w.classes()).toContain('bg-softer')
    expect(w.text()).toBe('管理员')
  })
  it('variant=warning 输出警示色', () => {
    const w = mount(UiBadge, { props: { variant: 'warning' } })
    expect(w.classes()).toContain('text-amber-800')
  })
})

describe('UiIcon', () => {
  it('解析已知的 lucide 名称渲染 svg', () => {
    const w = mount(UiIcon, { props: { name: 'Search', size: 16 } })
    expect(w.find('svg').exists()).toBe(true)
  })
  it('未知名称不抛错（fallback）', () => {
    expect(() => mount(UiIcon, { props: { name: 'Nope' } })).not.toThrow()
  })
})

describe('P3 新增适配层', () => {
  it('UiCard 渲染 title 头与默认插槽', () => {
    const w = mount(UiCard, { props: { title: '静态报告' }, slots: { default: '<p>body</p>' } })
    expect(w.find('h3').text()).toBe('静态报告')
    expect(w.html()).toContain('body')
  })

  it('UiAlert 渲染 variant 对应 class', () => {
    const w = mount(UiAlert, { props: { variant: 'error', title: '语法错误' } })
    expect(w.classes()).toContain('text-red-700')
    expect(w.text()).toContain('语法错误')
  })

  it('UiEmpty 渲染 description', () => {
    const w = mount(UiEmpty, { props: { description: '暂无数据' } })
    expect(w.text()).toContain('暂无数据')
  })

  it('UiTextarea v-model 双向绑定', async () => {
    const w = mount(UiTextarea, { props: { modelValue: 'init' } })
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe('init')
    await w.setValue('next')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['next'])
  })
})

/**
 * ui/ 适配层最小用例（spec §5 / Plan Task 4）。
 * 仅断言渲染与 class 拼接，组件无业务逻辑。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { cn } from '@/lib/utils'
import UiBadge from '@/ui/UiBadge.vue'
import UiButton from '@/ui/UiButton.vue'
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

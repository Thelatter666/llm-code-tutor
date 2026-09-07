import { expect, test } from '@playwright/test'

/**
 * 全路由截图 + 外壳行为冒烟。
 *
 * 账号来自 `make seed` 的默认管理员（README 已公开此口令）。
 * 截图目录：`tests/screenshots/${SHOTS}`（默认 baseline）。
 *
 * 选择器刻意只用语义元素（nav / button / main），
 * 以便外壳重写后无需改动即可继续断言。
 */
const ADMIN = { username: 'admin', password: 'Admin@12345' }
const SHOT_DIR = `tests/screenshots/${process.env.SHOTS ?? 'baseline'}`

const ROUTES: Array<[name: string, path: string]> = [
  ['chat', '/chat'],
  ['code', '/code'],
  ['editor', '/editor'],
  ['knowledge', '/knowledge'],
  ['exercises', '/exercises'],
  ['mistakes', '/mistakes'],
  ['admin-knowledge', '/admin/knowledge'],
  ['admin-exercises', '/admin/exercises'],
  ['admin-users', '/admin/users'],
  ['admin-model-config', '/admin/model-config'],
  ['admin-logs', '/admin/logs'],
  ['admin-overview', '/admin/overview'],
  ['admin-anti-plagiarism', '/admin/anti-plagiarism'],
]

async function login(page: import('@playwright/test').Page) {
  await page.goto('/#/login')
  await page.fill('input[autocomplete="username"]', ADMIN.username)
  await page.fill('input[autocomplete="current-password"]', ADMIN.password)
  await page.click('button:has-text("登录")')
  await page.waitForSelector('[aria-label="功能导航"]')
}

test('登录页', async ({ page }) => {
  await page.goto('/#/login')
  await expect(page.locator('h2')).toContainText('智能编程教学辅助系统')
  await page.screenshot({ path: `${SHOT_DIR}/login.png` })
})

test('已登录：13 个路由截图 + 导航项断言', async ({ page }) => {
  await login(page)
  await expect(page.locator('[aria-label="功能导航"] button')).toHaveCount(13)

  for (const [name, path] of ROUTES) {
    await page.goto(`/#${path}`)
    // 等到路由真正切换：仅凭 main 在会因 SPA 还没切到目标路由就提前截图
    await page.waitForURL((url) => url.hash === `#${path}`)
    // 表格/编辑器页有加载态与 1s 轮询，留一拍再截
    await page.waitForTimeout(500)
    await page.screenshot({ path: `${SHOT_DIR}/${name}.png` })
  }
})

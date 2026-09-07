import { defineConfig, devices } from '@playwright/test'

/**
 * 视觉回归配置（ADR-0012）。
 *
 * 服务由外部提供：`make dev`（前端 5173 + 后端 8000）或 `make serve`（单端口 8000）。
 * 截图目录由环境变量 SHOTS 决定：`baseline`（基线）/ `actual`（本次产出），
 * 差异由人工比对，不作为自动断言门禁。
 */
export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './tests/screenshots/results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    viewport: { width: 1440, height: 900 },
    ...devices['Desktop Chrome'],
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})

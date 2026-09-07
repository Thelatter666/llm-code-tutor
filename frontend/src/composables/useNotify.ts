/**
 * 全局通知：封装 Element Plus ElMessage。
 * 页面通过 useNotify() 获取 success/info/warning/error，
 * 不直接 import el-* —— 后续迁 shadcn-vue Sonner 时只改本文件。
 * `raw` 透传完整 options（如测试连接需要 8s 停留 + 可关闭）。
 */
import { ElMessage } from 'element-plus'

export function useNotify() {
  return {
    success: (m: string) => ElMessage.success(m),
    info: (m: string) => ElMessage.info(m),
    warning: (m: string) => ElMessage.warning(m),
    error: (m: string) => ElMessage.error(m),
    raw: (options: Parameters<typeof ElMessage>[0]) => ElMessage(options),
  }
}

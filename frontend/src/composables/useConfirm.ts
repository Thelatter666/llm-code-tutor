/**
 * 二次确认：封装 Element Plus ElMessageBox.confirm。
 * 返回 boolean（确认 = true，取消 = false），避免页面里重复写 try/catch。
 */
import { ElMessageBox } from 'element-plus'

export function useConfirm() {
  return async (message: string, title = '确认'): Promise<boolean> => {
    try {
      await ElMessageBox.confirm(message, title, { type: 'warning' })
      return true
    } catch {
      return false
    }
  }
}

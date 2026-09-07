import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** shadcn-vue 约定的类名合并工具（ADR-0011）。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

<script setup lang="ts">
/** 对话框：封装 el-dialog，标题/宽度走 props，内容与底部走插槽 */
import { ElDialog } from 'element-plus'

withDefaults(defineProps<{ title?: string; width?: string }>(), { title: '', width: '480px' })
const visible = defineModel<boolean>({ default: false })
</script>

<template>
  <ElDialog v-model="visible" :title="title" :width="width" destroy-on-close>
    <slot />
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </ElDialog>
</template>

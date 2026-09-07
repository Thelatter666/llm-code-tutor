<script setup lang="ts">
/**
 * 拖拽上传：封装 el-upload。
 * http-request 被本组件接管 —— 页面只拿到 File[]，不接触 UploadRequestOptions。
 */
import type { UploadRequestOptions } from 'element-plus'
import { ElUpload } from 'element-plus'

withDefaults(defineProps<{ accept?: string; multiple?: boolean }>(), { multiple: true })
const emit = defineEmits<{ files: [files: File[]] }>()

function onRequest(options: UploadRequestOptions) {
  emit('files', [options.file as File])
  return Promise.resolve()
}
</script>

<template>
  <ElUpload drag :http-request="onRequest" :show-file-list="false" :accept="accept" :multiple="multiple">
    <slot />
  </ElUpload>
</template>

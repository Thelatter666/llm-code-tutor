<script setup lang="ts">
/** 卡片：新层级观感的落点（bg-surface + rounded-panel + shadow-e2） */
withDefaults(defineProps<{ title?: string; padded?: boolean }>(), { padded: true })
</script>

<template>
  <section class="rounded-panel border border-line bg-surface shadow-panel">
    <header v-if="title || $slots.header" class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
      <h3 v-if="title" class="text-md font-semibold text-ink">{{ title }}</h3>
      <slot name="header" />
    </header>
    <div :class="padded ? 'p-4' : ''">
      <slot />
    </div>
    <footer v-if="$slots.footer" class="border-t border-line px-4 py-3">
      <slot name="footer" />
    </footer>
  </section>
</template>

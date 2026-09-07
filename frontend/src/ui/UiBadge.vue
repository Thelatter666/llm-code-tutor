<script setup lang="ts">
import { cva, type VariantProps } from 'class-variance-authority'
import { computed } from 'vue'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-xs font-medium',
  {
    variants: {
      variant: {
        primary: 'bg-brand/10 text-brand',
        warning: 'bg-amber-100 text-amber-800',
        muted: 'bg-softer text-muted-ink',
        danger: 'bg-red-100 text-red-700',
      },
    },
    defaultVariants: { variant: 'muted' },
  },
)
type BadgeVariants = VariantProps<typeof badgeVariants>
const props = withDefaults(
  defineProps<{ variant?: BadgeVariants['variant']; class?: string }>(),
  { variant: 'muted' },
)
const classes = computed(() => cn(badgeVariants({ variant: props.variant }), props.class))
</script>

<template>
  <span :class="classes">
    <slot />
  </span>
</template>

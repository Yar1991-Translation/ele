<script setup>
/** 按钮：variant=primary/stop/ghost/default，size=sm/md，loading 时禁用并显示转圈。 */
defineProps({
  variant: { type: String, default: "default" },
  size: { type: String, default: "md" },
  loading: Boolean,
  disabled: Boolean,
  block: Boolean,
});
</script>

<template>
  <button class="btn" :class="[variant, size, { block }]"
          :disabled="disabled || loading" :aria-busy="loading || undefined">
    <span v-if="loading" class="spin" aria-hidden="true"></span>
    <slot />
  </button>
</template>

<style scoped>
.btn.block{width:100%}
.spin{width:13px;height:13px;border-radius:50%;flex:none;
  border:2px solid currentColor;border-top-color:transparent;
  animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>

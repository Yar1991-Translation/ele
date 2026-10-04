<script setup>
/** 小徽标：tone=accent/green/red/blue/默认灰。 */
defineProps({
  tone: { type: String, default: "" },
  title: { type: String, default: "" },
});
</script>

<template>
  <span class="badge" :class="tone" :title="title || undefined"><slot /></span>
</template>

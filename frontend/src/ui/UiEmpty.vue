<script setup>
/** 空状态：一句「这是什么」+「下一步做什么」。对小白比空白有用得多。 */
defineProps({
  title: { type: String, default: "这里还没有内容" },
  hint: { type: String, default: "" },
  icon: { type: String, default: "○" },
});
</script>

<template>
  <div class="empty">
    <div class="ico" aria-hidden="true">{{ icon }}</div>
    <p class="ti">{{ title }}</p>
    <p v-if="hint" class="hp">{{ hint }}</p>
    <div v-if="$slots.default" class="act"><slot /></div>
  </div>
</template>

<style scoped>
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:var(--sp-2);padding:var(--sp-7) var(--sp-5);text-align:center;
  border:1px dashed var(--line2);border-radius:var(--r-lg);background:var(--surface)}
.ico{font-size:26px;color:var(--ink3);line-height:1}
.ti{font-size:var(--fs-base);font-weight:600;color:var(--ink2)}
.hp{font-size:var(--fs-sm);color:var(--ink3);max-width:46ch;line-height:1.7}
.act{margin-top:var(--sp-3);display:flex;gap:var(--sp-2)}
</style>

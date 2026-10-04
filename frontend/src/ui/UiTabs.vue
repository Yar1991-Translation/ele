<script setup>
/** 标签页：items=[{key,label,count?}]，v-model 绑当前 key。 */
defineProps({
  items: { type: Array, default: () => [] },
  modelValue: String,
});
defineEmits(["update:modelValue"]);
</script>

<template>
  <div class="tabs" role="tablist">
    <button v-for="it in items" :key="it.key" role="tab"
            class="tab" :class="{ on: it.key === modelValue }"
            :aria-selected="it.key === modelValue"
            @click="$emit('update:modelValue', it.key)">
      {{ it.label }}
      <span v-if="it.count !== undefined" class="n">{{ it.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.tabs{display:flex;gap:var(--sp-1);border-bottom:1px solid var(--line);flex-wrap:wrap}
.tab{padding:var(--sp-2) var(--sp-3);font-size:var(--fs-base);color:var(--ink2);
  border-bottom:2px solid transparent;margin-bottom:-1px;
  transition:color var(--dur-fast),border-color var(--dur-fast)}
.tab:hover{color:var(--ink)}
.tab.on{color:var(--accent-deep);border-bottom-color:var(--accent);font-weight:600}
.n{margin-left:5px;font-size:var(--fs-xs);color:var(--ink3);
  background:var(--sunken);padding:0 6px;border-radius:var(--r-full)}
.tab.on .n{background:var(--accent-soft);color:var(--accent-deep)}
</style>

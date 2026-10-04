<script setup>
/** 进度条：label 显示「章节 2/5」这类文字，percent 0~100。 */
import { computed } from "vue";

const props = defineProps({
  label: { type: String, default: "" },
  percent: { type: Number, default: 0 },
  indeterminate: Boolean,
});
const w = computed(() => Math.max(0, Math.min(100, props.percent)) + "%");
</script>

<template>
  <div class="prog">
    <span v-if="label" class="lb">{{ label }}</span>
    <span class="track" role="progressbar"
          :aria-valuenow="indeterminate ? undefined : Math.round(percent)"
          aria-valuemin="0" aria-valuemax="100" :aria-label="label || '进度'">
      <i :class="{ indet: indeterminate }" :style="indeterminate ? {} : { width: w }"></i>
    </span>
  </div>
</template>

<style scoped>
.prog{display:flex;align-items:center;gap:var(--sp-2);min-width:0}
.lb{font:500 var(--fs-xs)/1 var(--mono);color:var(--ink2);white-space:nowrap}
.track{display:block;flex:1;min-width:60px;height:6px;border-radius:var(--r-full);
  background:var(--sunken);overflow:hidden}
.track i{display:block;height:100%;border-radius:var(--r-full);
  background:linear-gradient(90deg,var(--accent),var(--accent-deep));
  transition:width var(--dur-slow) var(--ease)}
.track i.indet{width:35%;animation:slide 1.2s var(--ease) infinite}
@keyframes slide{0%{margin-left:-35%}100%{margin-left:100%}}
</style>

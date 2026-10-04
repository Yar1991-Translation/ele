<script setup>
/** 滑杆：显示当前值与两端刻度文字。 */
defineProps({
  modelValue: Number,
  min: { type: Number, default: 0 },
  max: { type: Number, default: 100 },
  step: { type: Number, default: 1 },
  unit: { type: String, default: "" },
  minLabel: { type: String, default: "" },
  maxLabel: { type: String, default: "" },
});
defineEmits(["update:modelValue"]);
</script>

<template>
  <div class="slider">
    <div class="row">
      <input type="range" :min="min" :max="max" :step="step" :value="modelValue"
             :aria-valuetext="`${modelValue}${unit}`"
             @input="$emit('update:modelValue', Number($event.target.value))">
      <output class="val">{{ modelValue }}{{ unit }}</output>
    </div>
    <div v-if="minLabel || maxLabel" class="ends">
      <span>{{ minLabel }}</span><span>{{ maxLabel }}</span>
    </div>
  </div>
</template>

<style scoped>
.slider{display:flex;flex-direction:column;gap:var(--sp-1)}
.row{display:flex;align-items:center;gap:var(--sp-3)}
input[type=range]{flex:1;padding:0;height:6px;accent-color:var(--accent);
  background:transparent;border:none}
.val{flex:none;min-width:52px;text-align:right;font:600 var(--fs-sm) var(--mono);
  color:var(--accent-deep)}
.ends{display:flex;justify-content:space-between;font-size:var(--fs-xs);color:var(--ink3)}
</style>

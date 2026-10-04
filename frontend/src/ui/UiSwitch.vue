<script setup>
/** 开关：带标题与说明，说明换行显示（比 hover 提示对小白友好）。 */
import { computed } from "vue";

const props = defineProps({
  modelValue: Boolean,
  label: { type: String, default: "" },
  help: { type: String, default: "" },
  disabled: Boolean,
});
const emit = defineEmits(["update:modelValue"]);
const on = computed({
  get: () => !!props.modelValue,
  set: (v) => emit("update:modelValue", v),
});
</script>

<template>
  <label class="sw" :class="{ on, disabled }">
    <input type="checkbox" v-model="on" :disabled="disabled" class="sr">
    <span class="track" aria-hidden="true"><span class="knob"></span></span>
    <span class="body">
      <span class="lb">{{ label }}</span>
      <span v-if="help" class="hp">{{ help }}</span>
    </span>
  </label>
</template>

<style scoped>
.sw{display:flex;align-items:flex-start;gap:var(--sp-3);cursor:pointer;
  padding:var(--sp-1) 0;user-select:none}
.sw.disabled{opacity:.5;cursor:not-allowed}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.track{flex:none;width:38px;height:22px;border-radius:var(--r-full);
  background:var(--line2);position:relative;transition:background var(--dur-med) var(--ease);
  margin-top:2px}
.knob{position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;
  background:#fff;box-shadow:var(--shadow-sm);transition:transform var(--dur-med) var(--ease)}
.on .track{background:var(--accent)}
.on .knob{transform:translateX(16px)}
.sw:focus-within .track{box-shadow:var(--focus-ring)}
.body{display:flex;flex-direction:column;gap:2px;min-width:0}
.lb{font-size:var(--fs-sm);font-weight:600;color:var(--ink);line-height:1.5}
.hp{font-size:var(--fs-xs);color:var(--ink3);line-height:1.65}
</style>

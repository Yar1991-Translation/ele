<script setup>
/** 下拉：options=[{value,label}]，也可给字符串数组或 [值,标签] 对
 *  （config_schema 的 choices 就是 [值,标签] 对，别让它渲染成空项）。 */
import { computed } from "vue";

const props = defineProps({
  modelValue: [String, Number],
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: "" },
  disabled: Boolean,
});
const emit = defineEmits(["update:modelValue"]);
const items = computed(() => props.options.map(o => {
  if (typeof o === "string") return { value: o, label: o };
  if (Array.isArray(o)) return { value: o[0], label: o[1] ?? o[0] };
  return o;
}));
</script>

<template>
  <select :value="modelValue" :disabled="disabled"
          @change="emit('update:modelValue', $event.target.value)">
    <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
    <option v-for="o in items" :key="o.value" :value="o.value">{{ o.label }}</option>
  </select>
</template>

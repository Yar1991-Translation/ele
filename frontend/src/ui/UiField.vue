<script setup>
/** 表单字段容器：标签 + 说明 + 控件 + 错误。
 *  说明写人话，不用术语——这是配置页对小白友好的关键。 */
defineProps({
  label: { type: String, default: "" },
  help: { type: String, default: "" },
  unit: { type: String, default: "" },
  required: Boolean,
  error: { type: String, default: "" },
});
</script>

<template>
  <div class="field" :class="{ invalid: !!error }">
    <div class="flabel">
      <span class="ftext">{{ label }}</span>
      <em v-if="required" class="req">必填</em>
      <span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <p v-if="help" class="fhelp">{{ help }}</p>
    <div class="fctl"><slot /></div>
    <p v-if="error" class="ferr" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.field{display:flex;flex-direction:column;gap:var(--sp-1);min-width:0}
.flabel{display:flex;align-items:baseline;gap:var(--sp-2);flex-wrap:wrap}
.ftext{font-size:var(--fs-sm);font-weight:600;color:var(--ink)}
.req{font-style:normal;font-size:var(--fs-xs);color:var(--red);
  background:var(--red-soft);padding:0 6px;border-radius:var(--r-full)}
.unit{font-size:var(--fs-xs);color:var(--ink3)}
.fhelp{margin:0;font-size:var(--fs-xs);line-height:1.65;color:var(--ink3)}
.ferr{margin:0;font-size:var(--fs-xs);color:var(--red)}
.field.invalid input,.field.invalid select,.field.invalid textarea{border-color:var(--red)}
</style>

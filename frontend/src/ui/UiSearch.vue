<script setup>
/** 搜索框：带清除按钮，v-model。 */
import { ref, watch } from "vue";

const props = defineProps({
  modelValue: String,
  placeholder: { type: String, default: "搜索…" },
});
const emit = defineEmits(["update:modelValue"]);
const local = ref(props.modelValue || "");
watch(() => props.modelValue, v => { if (v !== local.value) local.value = v || ""; });
watch(local, v => emit("update:modelValue", v));
</script>

<template>
  <div class="search">
    <span class="ico" aria-hidden="true">⌕</span>
    <input v-model="local" type="search" :placeholder="placeholder"
           aria-label="搜索">
    <button v-if="local" class="clr" aria-label="清空搜索" @click="local = ''">×</button>
  </div>
</template>

<style scoped>
.search{position:relative;display:flex;align-items:center}
.search input{padding-left:30px;padding-right:28px}
.ico{position:absolute;left:10px;color:var(--ink3);pointer-events:none;font-size:15px}
.clr{position:absolute;right:6px;width:20px;height:20px;border-radius:50%;
  color:var(--ink3);font-size:15px;line-height:1}
.clr:hover{background:var(--hover);color:var(--ink)}
input::-webkit-search-cancel-button{display:none}
</style>

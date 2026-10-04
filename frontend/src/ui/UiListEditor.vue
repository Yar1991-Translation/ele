<script setup>
/** 行式列表编辑器：提供商（providerlist）与团队成员（agentlist）这类
 *  list-of-dict 配置的通用编辑器，替代裸文本框。
 *  columns: [{key,label,placeholder,type:'text'|'password'|'select',options,width(flex)}] */
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  columns: { type: Array, required: true },
  newRow: { type: Object, default: () => ({}) },
  addLabel: { type: String, default: "添加" },
  emptyHint: { type: String, default: "还没有条目" },
});
const emit = defineEmits(["update:modelValue", "change"]);

function rows(){ return Array.isArray(props.modelValue) ? props.modelValue : []; }
function set(i, key, val){
  emit("update:modelValue", rows().map((r, idx) => idx === i ? { ...r, [key]: val } : r));
  emit("change");
}
function add(){
  emit("update:modelValue", [...rows(), { ...props.newRow }]);
  emit("change");
}
function remove(i){
  emit("update:modelValue", rows().filter((_, idx) => idx !== i));
  emit("change");
}
</script>

<template>
  <div class="lre">
    <div class="head">
      <span v-for="c in columns" :key="c.key" class="hcell" :style="{ flex: c.width || '1' }">
        {{ c.label }}</span>
      <span class="hcell hdel"></span>
    </div>
    <div v-if="!rows().length" class="empty">{{ emptyHint }}</div>
    <div v-for="(row, i) in rows()" :key="i" class="row">
      <template v-for="c in columns" :key="c.key">
        <select v-if="c.type === 'select'" class="in" :value="row[c.key] ?? ''"
                :style="{ flex: c.width || '1' }"
                @change="set(i, c.key, $event.target.value)">
          <option v-for="o in (c.options || [])" :key="o[0]" :value="o[0]">{{ o[1] }}</option>
        </select>
        <input v-else class="in" :type="c.type || 'text'" :value="row[c.key] ?? ''"
               :placeholder="c.placeholder || c.label" :style="{ flex: c.width || '1' }"
               @input="set(i, c.key, $event.target.value)">
      </template>
      <button class="del" type="button" title="删除这一行" @click="remove(i)">✕</button>
    </div>
    <button class="add" type="button" @click="add">＋ {{ addLabel }}</button>
  </div>
</template>

<style scoped>
.lre{display:flex;flex-direction:column;gap:var(--sp-2);min-width:0}
.head{display:flex;gap:var(--sp-2)}
.hcell{font-size:var(--fs-xs);color:var(--ink3)}
.hdel{flex:0 0 28px}
.row{display:flex;gap:var(--sp-2);align-items:center}
.in{min-width:0}
.empty{font-size:var(--fs-xs);color:var(--ink3);padding:var(--sp-2) 0}
.del{flex:0 0 28px;height:32px;border:1px solid var(--line2);border-radius:var(--r-sm);
  background:var(--surface);color:var(--ink3);cursor:pointer}
.del:hover{color:var(--red);border-color:var(--red)}
.add{align-self:flex-start;font-size:var(--fs-sm);padding:4px 12px;cursor:pointer;
  border:1px dashed var(--line2);border-radius:var(--r-sm);background:transparent;
  color:var(--ink2)}
.add:hover{border-color:var(--accent);color:var(--accent)}
</style>

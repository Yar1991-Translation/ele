<script setup>
/** 成果库：生成的文章、讨论记录、提示词分开摆；可搜索、删除、重命名、导出、两篇对比。 */
import { reactive, ref, computed, onMounted, watch } from "vue";
import { useStore, api, toast, openReader, openCompare, draftFromOutput, refreshData } from "../store.js";
import { UiCard, UiTabs, UiSearch, UiBtn, UiEmpty, UiDialog, UiField } from "../ui";

const s = useStore();
const tab = ref("article");
const query = ref("");
const busy = ref("");
const renaming = ref(null);   // {from, to}
const sortDesc = ref(true);   // 文件名带时间戳，按名字排就是按时间排
const picked = ref([]);       // 勾选对比的两篇（最多两个文件名）

const TABS = computed(() => {
  const g = s.stats.output_groups || {};
  return [
    { key: "article", label: "生成的文章", count: (g.article || []).length },
    { key: "discussion", label: "讨论记录", count: (g.discussion || []).length },
    { key: "prompt", label: "提示词", count: (g.prompt || []).length },
  ];
});

const files = computed(() => {
  const g = s.stats.output_groups || {};
  let all = g[tab.value] || (tab.value === "article" ? (s.stats.outputs || []) : []);
  const q = query.value.trim();
  if (q) all = all.filter(n => n.includes(q));
  return [...all].sort((a, b) => sortDesc.value ? b.localeCompare(a) : a.localeCompare(b));
});

function togglePick(name){
  const i = picked.value.indexOf(name);
  if (i >= 0) picked.value.splice(i, 1);
  else picked.value.push(name);
  if (picked.value.length > 2) picked.value.shift();   // 超出两篇时挤掉最早选的
}
async function comparePicked(){
  if (picked.value.length !== 2) return;
  try {
    await openCompare(picked.value[0], picked.value[1]);
    picked.value = [];
  } catch (e) { toast(String(e.message || e), true); }
}

const pretty = (n) => n.replace(/^\d{8}-\d{6}_/, "").replace(/\.md$/, "");

async function open(name){
  try {
    const j = await api("/api/file/output/" + encodeURIComponent(name));
    openReader({ title: pretty(name), subtitle: name, html: null, md: j.content, file: name });
  } catch (e) { toast(String(e.message || e), true); }
}

async function exportFile(name){
  window.open("/api/output/" + encodeURIComponent(name) + "/export", "_blank");
}

async function remove(name){
  if (!confirm("删除「" + pretty(name) + "」？这一步不可撤销。")) return;
  busy.value = name;
  try {
    await api("/api/output/" + encodeURIComponent(name), { method: "DELETE" });
    toast("已删除");
    await refreshData();
  } catch (e) { toast(String(e.message || e), true); }
  busy.value = "";
}

async function doRename(){
  const { from, to } = renaming.value;
  if (!to || !to.trim()) return;
  busy.value = from;
  try {
    await api("/api/output/" + encodeURIComponent(from) + "/rename",
              { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ to: to.trim() }) });
    toast("已重命名");
    renaming.value = null;
    await refreshData();
  } catch (e) { toast(String(e.message || e), true); }
  busy.value = "";
}

onMounted(() => { /* stats 由 store 轮询刷新 */ });
</script>

<template>
  <div class="view">
    <UiCard>
      <template #extra>
        <UiSearch v-model="query" placeholder="搜文件名或标题" />
        <UiBtn size="sm" @click="sortDesc = !sortDesc">
          {{ sortDesc ? "新 → 旧" : "旧 → 新" }}
        </UiBtn>
      </template>

      <UiTabs v-model="tab" :items="TABS" />

      <UiEmpty v-if="!files.length" :title="tab === 'article' ? '还没有生成过文章' : '这里还是空的'"
               :hint="tab === 'article' ? '到「写作」页写下想法，生成后会出现在这里。'
                                       : (tab === 'prompt' ? '提示词可以在「设置 · 提示词」里编辑。' : '')"
               icon="✎" />

      <div v-else class="list">
        <div v-for="n in files" :key="n" class="row" :class="{ picked: picked.includes(n) }">
          <button class="name" @click="open(n)">
            <b>{{ pretty(n) }}</b>
            <span class="sub">{{ n }}</span>
          </button>
          <div class="ops">
            <UiBtn size="sm" ghost @click="open(n)">读</UiBtn>
            <UiBtn v-if="tab === 'article'" size="sm" ghost
                   :class="{ on: picked.includes(n) }" @click="togglePick(n)">
              {{ picked.includes(n) ? "✓ 对比中" : "对比" }}
            </UiBtn>
            <UiBtn size="sm" ghost @click="exportFile(n)">导出</UiBtn>
            <UiBtn size="sm" ghost @click="renaming = { from: n, to: pretty(n) }">重命名</UiBtn>
            <UiBtn v-if="tab === 'article'" size="sm" ghost
                   @click="draftFromOutput(n, 'team')">团队润色</UiBtn>
            <UiBtn size="sm" variant="stop" :loading="busy === n" @click="remove(n)">删除</UiBtn>
          </div>
        </div>
      </div>

      <!-- 对比浮条：选满两篇后出现 -->
      <div v-if="picked.length" class="cmpbar">
        <span>已选 {{ picked.length }} / 2 篇</span>
        <UiBtn size="sm" variant="primary" :disabled="picked.length !== 2" @click="comparePicked">
          对比这 {{ picked.length === 2 ? "两" : picked.length }} 篇
        </UiBtn>
        <UiBtn size="sm" ghost @click="picked = []">清空</UiBtn>
      </div>
    </UiCard>

    <UiDialog :open="!!renaming" title="重命名" desc="文件名会显示在成果库里。"
              @close="renaming = null">
      <UiField label="新名字">
        <input v-model="renaming.to" type="text" @keyup.enter="doRename">
      </UiField>
      <template #footer>
        <UiBtn @click="renaming = null">取消</UiBtn>
        <UiBtn variant="primary" :loading="!!busy" @click="doRename">确定</UiBtn>
      </template>
    </UiDialog>
  </div>
</template>

<style scoped>
.view{display:flex;flex-direction:column;gap:var(--sp-4)}
.list{display:flex;flex-direction:column;gap:var(--sp-2);margin-top:var(--sp-4)}
.row{display:flex;align-items:center;gap:var(--sp-3);
  padding:var(--sp-2) var(--sp-3);border:1px solid var(--line);
  border-radius:var(--r-md);background:var(--surface)}
.row:hover{border-color:var(--line2);background:var(--hover)}
.row.picked{border-color:var(--accent);background:var(--accent-soft)}
.ops :deep(.btn.on){color:var(--accent-deep);border-color:var(--accent);background:var(--accent-soft)}
.cmpbar{display:flex;align-items:center;gap:var(--sp-3);margin-top:var(--sp-4);
  padding:var(--sp-2) var(--sp-3);border:1px dashed var(--accent);
  border-radius:var(--r-md);font-size:var(--fs-sm);color:var(--accent-deep)}
.cmpbar span{flex:1}
.name{flex:1;display:flex;flex-direction:column;gap:2px;text-align:left;min-width:0}
.name b{font-size:var(--fs-base);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.name:hover b{color:var(--accent-deep)}
.name .sub{font:var(--fs-xs) var(--mono);color:var(--ink3);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ops{display:flex;gap:2px;flex:none}
</style>

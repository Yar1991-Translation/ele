<script setup>
/** 素材页：先跑阶段（爬取→过滤→蒸馏→角色卡），再看产物。
 *  文章表格现在能看到 LLM 判的分类了——以前判完完全不可见。 */
import { reactive, ref, computed, onMounted, watch } from "vue";
import { useStore, api, runStage, stopStage, toast, openReader, openPost, uploadPersonas, deletePersona } from "../store.js";
import { UiCard, UiTabs, UiSearch, UiSelect, UiBtn, UiBadge, UiEmpty } from "../ui";

const s = useStore();
const tab = ref("posts");

// ---- 阶段 ----
const STEPS = [
  { key: "crawl", label: "① 爬取", desc: "从 Lofter 抓文章", btn: "开始爬取",
    count: () => s.stats.posts, unit: "篇" },
  { key: "filter", label: "② 过滤", desc: "排除乙女向、图片帖、碎片帖", btn: "开始过滤",
    count: () => s.stats.filtered, unit: "篇保留" },
  { key: "distill", label: "③ 蒸馏", desc: "提炼成知识库", btn: "开始蒸馏",
    count: () => (s.stats.knowledge || []).length, unit: "份" },
  { key: "chars", label: "④ 角色卡", desc: "从同人文提炼人物形象", btn: "蒸馏角色卡",
    count: () => s.stats.charcards, unit: "张" },
];

// ---- 文章表 ----
const list = reactive({ kind: "filtered", q: "", article_type: "", cp_combo: "",
                        ending: "", sort: "", order: "", page: 1,
                        total: 0, size: 30, items: [] });
const loading = ref(false);

const TYPE_OPTS = [{ value: "", label: "全部类型" },
                   { value: "单人向", label: "单人向" }, { value: "CP向", label: "CP向" },
                   { value: "其他", label: "其他" }];
const CP_OPTS = [{ value: "", label: "全部组合" },
                 { value: "微量", label: "微量" }, { value: "男女", label: "男女" },
                 { value: "男男", label: "男男" }, { value: "女女", label: "女女" },
                 { value: "多CP", label: "多CP" }, { value: "无CP", label: "无CP" }];
const ENDING_OPTS = [{ value: "", label: "全部结局" },
                     { value: "HE", label: "HE（好结局）" }, { value: "BE", label: "BE（坏结局）" },
                     { value: "开放式", label: "开放式" }, { value: "未知", label: "未知" }];

// 点表头切换排序：降序 -> 升序 -> 恢复默认
function toggleSort(key){
  if (list.sort !== key){ list.sort = key; list.order = "desc"; }
  else if (list.order === "desc") list.order = "asc";
  else { list.sort = ""; list.order = ""; }
}
function sortMark(key){
  return list.sort === key ? (list.order === "desc" ? " ↓" : " ↑") : "";
}

async function loadPosts(){
  loading.value = true;
  try {
    const qs = new URLSearchParams({ kind: list.kind, page: list.page,
      size: list.size, q: list.q, article_type: list.article_type,
      cp_combo: list.cp_combo, ending: list.ending,
      sort: list.sort, order: list.order });
    const j = await api("/api/posts?" + qs);
    list.total = j.total;
    list.items = j.items;
  } catch (e) { toast(String(e.message || e), true); }
  loading.value = false;
}

watch(() => [list.kind, list.q, list.article_type, list.cp_combo, list.ending,
             list.sort, list.order], () => { list.page = 1; loadPosts(); });
watch(() => list.page, loadPosts);

const pages = computed(() => Math.max(1, Math.ceil(list.total / list.size)));

// ---- 知识库 / 人物卡 / 设定与剧情 ----
const knowTab = ref("knowledge");
const knowledge = computed(() => s.stats.knowledge || []);
const charCards = ref([]);
const personaFiles = ref([]);
const personaInput = ref(null);
const loreFiles = ref([]);
const loreInput = ref(null);

async function loadAssets(){
  try {
    const [cc, ps, lf] = await Promise.all([api("/api/character-cards"), api("/api/personas"),
                                            api("/api/lore")]);
    charCards.value = cc.files;
    personaFiles.value = ps.files;
    loreFiles.value = lf.files;
  } catch { /* 首次加载可能还没数据 */ }
}

// 文件接口按类型分流：知识库在 /api/file/knowledge，人物卡各有专用接口
function fileUrl(kind, name){
  if (kind === "personas") return "/api/personas/" + encodeURIComponent(name);
  if (kind === "charcards") return "/api/character-cards/" + encodeURIComponent(name);
  return "/api/file/" + kind + "/" + encodeURIComponent(name);
}
const KIND_LABEL = { knowledge: "知识库", personas: "官方人物卡",
                     charcards: "蒸馏人物卡", output: "文件" };

async function openFile(kind, name){
  try {
    const j = await api(fileUrl(kind, name));
    openReader({ title: j.name || name, subtitle: KIND_LABEL[kind] || "",
                 html: `<pre class="md">${j.content.replace(/[&<>]/g, c =>
                   ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))}</pre>` });
  } catch (e) { toast(String(e.message || e), true); }
}

async function onUpload(ev){
  try { await uploadPersonas(ev.target.files); loadAssets(); }
  catch (e) { toast(String(e.message || e), true); }
  ev.target.value = "";
}

async function removePersona(file){
  if (!confirm("删除人物卡「" + file + "」？这一步不可撤销。")) return;
  try { await deletePersona(file); loadAssets(); }
  catch (e) { toast(String(e.message || e), true); }
}

// ---- 设定与剧情（data/lore/，写作查询工具的资料来源） ----
function loreUrl(rel){
  return "/api/lore/" + encodeURIComponent(rel).replaceAll("%2F", "/");
}
async function openLore(rel){
  try {
    const j = await api(loreUrl(rel));
    openReader({ title: rel, subtitle: "设定与剧情",
                 html: `<pre class="md">${j.content.replace(/[&<>]/g, c =>
                   ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))}</pre>` });
  } catch (e) { toast(String(e.message || e), true); }
}
async function onLoreUpload(ev){
  try {
    const fd = new FormData();
    for (const f of ev.target.files) fd.append("files", f);
    const r = await fetch("/api/lore", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({ error: r.statusText }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    toast("已导入：" + j.saved.join("、"));
    loadAssets();
  } catch (e) { toast(String(e.message || e), true); }
  ev.target.value = "";
}
async function removeLore(rel){
  if (!confirm("删除「" + rel + "」？这一步不可撤销。")) return;
  try {
    const r = await fetch(loreUrl(rel), { method: "DELETE" });
    const j = await r.json().catch(() => ({ error: r.statusText }));
    if (!r.ok) throw new Error(j.error || r.statusText);
    loadAssets();
  } catch (e) { toast(String(e.message || e), true); }
}
function fmtSize(n){
  return n > 10240 ? (n / 1024).toFixed(1) + " KB" : n + " B";
}

// 下载一份文件（知识库/人物卡可读也可导出）
async function exportFile(kind, name){
  try {
    const j = await api(fileUrl(kind, name));
    const blob = new Blob([j.content], { type: "text/markdown;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (j.name || name).split("/").pop();
    if (!/\.md$|\.txt$/i.test(a.download)) a.download += ".md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (e) { toast(String(e.message || e), true); }
}

onMounted(() => { loadPosts(); loadAssets(); });
</script>

<template>
  <div class="view">
    <!-- 阶段 -->
    <div class="steps">
      <UiCard v-for="st in STEPS" :key="st.key" class="step">
        <div class="stop">
          <div>
            <h3>{{ st.label }}</h3>
            <p class="desc">{{ st.desc }}</p>
          </div>
          <div class="cnt"><b>{{ st.count() || 0 }}</b><span>{{ st.unit }}</span></div>
        </div>
        <UiBtn :disabled="!!s.running" :variant="st.key === 'crawl' ? 'primary' : 'default'"
               @click="runStage({ stage: st.key }).catch(e => toast(e.message, true))">
          {{ st.btn }}
        </UiBtn>
      </UiCard>
    </div>

    <p class="hint">一键跑完前 3 步：
      <UiBtn size="sm" :disabled="!!s.running"
             @click="runStage({ stage: 'runall' }).catch(e => toast(e.message, true))">
        一键跑素材
      </UiBtn>
      <UiBtn v-if="s.running" size="sm" variant="stop"
             @click="stopStage().catch(e => toast(e.message, true))">停止</UiBtn>
    </p>

    <!-- 产物 -->
    <UiCard>
      <template #extra>
        <UiTabs v-model="knowTab" :items="[
          { key: 'posts', label: '文章', count: list.total },
          { key: 'knowledge', label: '知识库', count: knowledge.length },
          { key: 'personas', label: '人物卡', count: personaFiles.length + charCards.length },
          { key: 'lore', label: '设定与剧情', count: loreFiles.length },
        ]" />
      </template>

      <!-- 文章 -->
      <template v-if="knowTab === 'posts'">
        <div class="filters">
          <UiTabs v-model="list.kind" :items="[
            { key: 'filtered', label: '保留', count: s.stats.filtered },
            { key: 'excluded', label: '已排除', count: s.stats.excluded },
            { key: 'posts', label: '全部爬取', count: s.stats.posts },
          ]" />
          <UiSearch v-model="list.q" placeholder="搜标题、作者、标签" />
          <UiSelect v-model="list.article_type" :options="TYPE_OPTS" />
          <UiSelect v-model="list.cp_combo" :options="CP_OPTS" />
          <UiSelect v-model="list.ending" :options="ENDING_OPTS" />
        </div>

        <UiEmpty v-if="!list.items.length && !loading" title="没有匹配的文章"
                 hint="换一个筛选条件，或先跑一次爬取和过滤。" icon="▤" />

        <table v-else class="tbl">
          <thead>
            <tr>
              <th><button class="th" @click="toggleSort('title')">标题{{ sortMark("title") }}</button></th>
              <th>分类</th><th>结局</th><th>作者</th>
              <th><button class="th" @click="toggleSort('publish_time')">时间{{ sortMark("publish_time") }}</button></th>
              <th><button class="th" @click="toggleSort('hot')">热度{{ sortMark("hot") }}</button></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in list.items" :key="it.url">
              <td class="ti"><button class="lnk" @click="openPost(it.url)">{{ it.title }}</button>
                <span v-if="it.reason" class="why">{{ it.reason }}</span></td>
              <td><UiBadge v-if="it.category" tone="blue">{{ it.category }}</UiBadge>
                  <span v-else class="mute">—</span></td>
              <td><UiBadge v-if="it.ending && it.ending !== '未知'"
                          :tone="it.ending === 'BE' ? 'red' : it.ending === 'HE' ? 'green' : ''">
                  {{ it.ending }}</UiBadge>
                  <span v-else class="mute">—</span></td>
              <td class="mute">{{ it.author }}</td>
              <td class="mute mono">{{ it.publish_time }}</td>
              <td class="mono">{{ it.hot }}</td>
            </tr>
          </tbody>
        </table>

        <div v-if="pages > 1" class="pager">
          <UiBtn size="sm" :disabled="list.page <= 1" @click="list.page--">上一页</UiBtn>
          <span class="mono">{{ list.page }} / {{ pages }}</span>
          <UiBtn size="sm" :disabled="list.page >= pages" @click="list.page++">下一页</UiBtn>
        </div>
      </template>

      <!-- 知识库 -->
      <template v-else-if="knowTab === 'knowledge'">
        <UiEmpty v-if="!knowledge.length" title="还没有知识库"
                 hint="跑完「蒸馏」后，每个文章分类会生成一套（人设与关系／文风／桥段与爽点／雷点）。"
                 icon="▤" />
        <div v-else class="files">
          <div v-for="k in knowledge" :key="k" class="prow">
            <button class="fitem" @click="openFile('knowledge', k)">{{ k }}</button>
            <UiBtn size="sm" variant="ghost" @click="exportFile('knowledge', k)">导出</UiBtn>
          </div>
        </div>
      </template>

      <!-- 人物卡 -->
      <template v-else-if="knowTab === 'personas'">
        <div class="persona-head">
          <b>官方人物卡（最高优先级）</b>
          <UiBtn size="sm" @click="personaInput.click()">导入</UiBtn>
          <input ref="personaInput" type="file" multiple accept=".md,.txt"
                 hidden @change="onUpload">
        </div>
        <UiEmpty v-if="!personaFiles.length" title="还没有官方人物卡"
                 hint="点「导入」选 .md/.txt 文件，或直接把文件丢进 data/personas/。" icon="♙" />
        <div v-else class="files">
          <div v-for="f in personaFiles" :key="f.file" class="prow">
            <button class="fitem" @click="openFile('personas', f.file)">
              {{ f.file }}<span class="sub">{{ f.names.join("、") }}</span>
            </button>
            <UiBtn size="sm" variant="ghost" @click="exportFile('personas', f.file)">导出</UiBtn>
            <UiBtn size="sm" variant="ghost" @click="removePersona(f.file)">删除</UiBtn>
          </div>
        </div>

        <div class="persona-head">
          <b>蒸馏人物卡（同人语境形象）</b>
          <UiBtn size="sm" :disabled="!!s.running"
                 @click="runStage({ stage: 'chars' }).catch(e => toast(e.message, true))">
            重新蒸馏
          </UiBtn>
        </div>
        <UiEmpty v-if="!charCards.length" title="还没有蒸馏人物卡"
                 hint="从已爬的同人文里提炼每个角色在同人圈里的形象。" icon="♙" />
        <div v-else class="files">
          <div v-for="f in charCards" :key="f.file" class="prow">
            <button class="fitem" @click="openFile('charcards', f.name)">{{ f.name }}</button>
            <UiBtn size="sm" variant="ghost" @click="exportFile('charcards', f.name)">导出</UiBtn>
          </div>
        </div>
      </template>

      <!-- 设定与剧情 -->
      <template v-else-if="knowTab === 'lore'">
        <p class="lore-hint">这里的文件是世界观、组织、时间线、剧情梗概等**你认可的硬设定**：
          开启「写作前可查资料」后，AI 逐章动笔前可以按需查阅全文（写作设置里可关）。
          人物卡不用放这里——上面「人物卡」标签页里的会自动可查。</p>
        <div class="persona-head">
          <b>设定/剧情文件</b>
          <UiBtn size="sm" @click="loreInput.click()">导入</UiBtn>
          <input ref="loreInput" type="file" multiple accept=".md,.txt" hidden @change="onLoreUpload">
        </div>
        <UiEmpty v-if="!loreFiles.length" title="还没有设定文件"
                 hint="点「导入」上传 .md/.txt（世界观、设定集、剧情大纲…），或直接丢进 data/lore/。支持子目录。"
                 icon="▣" />
        <div v-else class="files">
          <div v-for="f in loreFiles" :key="f.rel" class="prow">
            <button class="fitem" @click="openLore(f.rel)">
              {{ f.rel }}<span class="sub">{{ fmtSize(f.size) }}</span>
            </button>
            <UiBtn size="sm" variant="ghost" @click="removeLore(f.rel)">删除</UiBtn>
          </div>
        </div>
      </template>
    </UiCard>
  </div>
</template>

<style scoped>
.view{display:flex;flex-direction:column;gap:var(--sp-4)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:var(--sp-3)}
.step{display:flex;flex-direction:column;gap:var(--sp-3)}
.stop{display:flex;justify-content:space-between;align-items:flex-start;gap:var(--sp-3)}
.cnt{text-align:right;flex:none}
.cnt b{font:700 var(--fs-xl) var(--mono);color:var(--accent-deep);display:block;line-height:1}
.cnt span{font-size:var(--fs-xs);color:var(--ink3)}
.hint{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;
  font-size:var(--fs-sm);color:var(--ink3);margin:0}

.filters{display:flex;gap:var(--sp-3);align-items:center;flex-wrap:wrap;
  margin-bottom:var(--sp-4)}
.filters :deep(.tabs){border-bottom:none;flex:1}
.filters :deep(select){width:auto;min-width:130px}
.filters :deep(.search){width:220px}

.tbl{width:100%;font-size:var(--fs-sm)}
.tbl th{text-align:left;padding:var(--sp-2) var(--sp-2);color:var(--ink3);
  font-weight:600;font-size:var(--fs-xs);border-bottom:1px solid var(--line);white-space:nowrap}
.tbl th .th{color:inherit;font:inherit;display:inline-flex;align-items:center;gap:2px}
.tbl th .th:hover{color:var(--accent-deep)}
.tbl td{padding:var(--sp-2);border-bottom:1px solid var(--line);vertical-align:top}
.tbl tr:hover td{background:var(--hover)}
.ti{max-width:420px}
.lnk{text-align:left;color:var(--ink);font-weight:500}
.lnk:hover{color:var(--accent-deep);text-decoration:underline}
.why{display:block;font-size:var(--fs-xs);color:var(--red);margin-top:2px}
.mute{color:var(--ink3)}
.mono{font:var(--fs-xs) var(--mono)}
.pager{display:flex;align-items:center;justify-content:center;gap:var(--sp-3);
  margin-top:var(--sp-4);font-size:var(--fs-sm)}

.files{display:flex;flex-direction:column;gap:var(--sp-2)}
.fitem{display:flex;flex-direction:column;gap:2px;text-align:left;
  padding:var(--sp-2) var(--sp-3);border:1px solid var(--line2);border-radius:var(--r-md);
  background:var(--surface);font-size:var(--fs-sm)}
.fitem:hover{border-color:var(--accent);background:var(--hover)}
.fitem .sub{font-size:var(--fs-xs);color:var(--ink3)}
.prow{display:flex;align-items:center;gap:var(--sp-2)}
.prow .fitem{flex:1}
.persona-head{display:flex;align-items:center;justify-content:space-between;
  gap:var(--sp-3);margin:var(--sp-5) 0 var(--sp-2);font-size:var(--fs-base)}
.persona-head:first-child{margin-top:0}
.lore-hint{font-size:var(--fs-xs);color:var(--ink3);line-height:1.7;
  margin:0 0 var(--sp-2)}
</style>

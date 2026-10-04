<script setup>
/** 提示词在线编辑：选模板 -> 改文字 -> 保存（自动备份），删掉 $占位符会被拒。
 *  变量说明表把 $变量翻译成人话，改之前先看懂再动手。 */
import { ref, computed, onMounted } from "vue";
import { api, toast } from "../store.js";
import { UiBtn, UiSelect, UiBadge, UiEmpty } from "../ui";

// $变量 -> 人话（程序运行时自动填入；表里查不到的按通用说法兜底）
const VAR_HELP = {
  idea: "你的想法（写作要求）",
  draft: "你粘贴的原稿全文",
  article: "待润色/审校的文章全文",
  chapter_text: "本章正文",
  chapter_json: "本章的结构化信息（大纲、要点）",
  chapter_no: "第几章",
  chapter_chars: "单章目标字数",
  n_chapters: "总章数",
  total_chapters: "总章数",
  length: "目标总字数",
  size_anchor: "篇幅锚点（各章字数参考）",
  title: "文章标题",
  story: "故事梗概",
  story_so_far: "已写内容的脉络小结",
  story_map: "全篇章节安排（含前情与待写走向）",
  requirements: "用户需求清单（点名情节/基调/禁忌）",
  verdict_note: "结局校验给出的问题诊断",
  spine: "全文骨架（一句话一章的主线）",
  prev: "上一章正文",
  prev_head: "上一章开头",
  prev_tail: "上一章结尾（衔接用）",
  partials: "各批的中间提炼结果",
  part_note: "分批合并的说明",
  personas: "注入的人物卡内容",
  knowledge: "注入的知识库内容",
  knowledge_source: "知识库的取材范围说明",
  bible: "写作圣经（全文设定档案）",
  target_type: "目标文章类型（单人向/CP向/其他）",
  cp_combo: "目标 CP 组合（微量/男女/男男/女女/多CP/无CP）",
  type_hint: "按类型给出的写作提示",
  ending: "目标结局（HE/BE/开放式/不限）",
  ending_text: "目标结局的通俗说明",
  plot_anchor: "情节锚点（必须出现的关键情节）",
  char: "当前蒸馏的角色名",
  articles: "该角色相关的文章摘录",
  schema: "要求的输出格式说明",
  stage_label: "提问发生的阶段",
  plan: "当前大纲（供提问参考）",
  max_questions: "本次最多提问数",
  reviews: "各位编辑的评审意见",
  member: "当前评审成员的视角说明",
  perspective: "成员的职责视角",
  round: "第几轮讨论",
  thinking_note: "思考强度使用说明",
};

const list = ref([]);
const current = ref("");       // 当前模板名
const content = ref("");
const vars = ref([]);
const backups = ref([]);
const backupPick = ref("");
const dirty = ref(false);
const saving = ref(false);
const err = ref("");

const pretty = (n) => n.replace(/\.md$/, "");

const varRows = computed(() => (vars.value || []).map(v => ({
  name: v, help: VAR_HELP[v] || "运行时自动填入的内容",
})));

async function loadList(){
  try {
    const j = await api("/api/prompts");
    list.value = j.items;
    if (!current.value && j.items.length) open(j.items[0].name);
  } catch (e) { toast("读取提示词列表失败：" + e.message, true); }
}

async function open(name){
  if (dirty.value && name !== current.value &&
      !confirm("「" + pretty(current.value) + "」有未保存的修改，放弃并切换？")) return;
  try {
    const j = await api("/api/prompts/" + encodeURIComponent(name));
    current.value = name;
    content.value = j.content;
    vars.value = j.vars;
    backups.value = j.backups || [];
    backupPick.value = "";
    dirty.value = false;
    err.value = "";
  } catch (e) { toast(String(e.message || e), true); }
}

async function save(){
  saving.value = true;
  err.value = "";
  try {
    const r = await api("/api/prompts/" + encodeURIComponent(current.value),
                        { method: "PUT", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ content: content.value }) });
    vars.value = r.vars;
    dirty.value = false;
    toast("已保存「" + pretty(current.value) + "」，旧版已自动备份");
    const j = await api("/api/prompts/" + encodeURIComponent(current.value));
    backups.value = j.backups || [];
  } catch (e) {
    err.value = String(e.message || e);
    toast(String(e.message || e), true);
  }
  saving.value = false;
}

async function restore(){
  if (!backupPick.value) return;
  if (!confirm("把「" + pretty(current.value) + "」回滚到 " + backupPick.value + "？当前内容会被覆盖。")) return;
  try {
    const r = await api("/api/prompts/" + encodeURIComponent(current.value) + "/restore",
                        { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ backup: backupPick.value }) });
    content.value = r.content;
    vars.value = r.vars;
    dirty.value = false;
    err.value = "";
    toast("已回滚到 " + backupPick.value);
  } catch (e) { toast(String(e.message || e), true); }
}

onMounted(loadList);
</script>

<template>
  <div class="pp">
    <aside class="plist">
      <p class="phd">模板（{{ list.length }}）</p>
      <button v-for="it in list" :key="it.name" class="pitem"
              :class="{ on: it.name === current }" @click="open(it.name)">
        <b>{{ pretty(it.name) }}</b>
        <span>{{ it.vars.length }} 个变量 · {{ it.chars }} 字</span>
      </button>
    </aside>

    <section class="pmain">
      <UiEmpty v-if="!current" title="没有可编辑的提示词"
               hint="prompts/ 目录下的 .md 模板都会列在这里。" icon="✎" />
      <template v-else>
        <header class="ph">
          <div>
            <b>{{ pretty(current) }}</b>
            <span class="fn">{{ current }}</span>
          </div>
          <div class="acts">
            <UiBtn variant="primary" :loading="saving" :disabled="!dirty" @click="save">
              保存（自动备份）
            </UiBtn>
          </div>
        </header>

        <p v-if="err" class="perr" role="alert">{{ err }}</p>

        <div class="vbox">
          <p class="vh">变量说明表 —— 这些 $占位符会被运行时的实际内容替换，<b>保存时不能删掉</b>：</p>
          <table class="vt">
            <thead><tr><th>占位符</th><th>会填进什么</th></tr></thead>
            <tbody>
              <tr v-for="r in varRows" :key="r.name">
                <td class="mono">${{ r.name }}</td>
                <td>{{ r.help }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <textarea v-model="content" class="pedit" spellcheck="false"
                  @input="dirty = true"></textarea>

        <div class="pbar">
          <span class="st">
            <UiBadge v-if="dirty" tone="accent">有未保存的修改</UiBadge>
            <UiBadge v-else tone="green">已是最新</UiBadge>
          </span>
          <template v-if="backups.length">
            <UiSelect v-model="backupPick" class="bsel"
                      :options="[{ value: '', label: '选择备份版本…' },
                                 ...backups.map(b => ({ value: b, label: b }))]" />
            <UiBtn size="sm" :disabled="!backupPick" @click="restore">回滚到该版</UiBtn>
          </template>
          <span v-else class="nb">还没有备份——第一次保存后会自动生成</span>
        </div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.pp{display:grid;grid-template-columns:220px 1fr;gap:var(--sp-4);align-items:start}
@media(max-width:820px){.pp{grid-template-columns:1fr}}
.plist{display:flex;flex-direction:column;gap:2px;max-height:480px;overflow-y:auto}
.phd{margin:0 0 var(--sp-2);font-size:var(--fs-xs);color:var(--ink3)}
.pitem{display:flex;flex-direction:column;gap:1px;text-align:left;
  padding:var(--sp-2) var(--sp-3);border-radius:var(--r-md);font-size:var(--fs-sm)}
.pitem:hover{background:var(--hover)}
.pitem.on{background:var(--accent-soft);color:var(--accent-deep)}
.pitem span{font-size:var(--fs-xs);color:var(--ink3)}
.pitem.on span{color:var(--accent-deep);opacity:.8}

.pmain{display:flex;flex-direction:column;gap:var(--sp-3);min-width:0}
.ph{display:flex;align-items:center;justify-content:space-between;gap:var(--sp-3)}
.ph b{font-size:var(--fs-md)}
.ph .fn{margin-left:var(--sp-2);font:var(--fs-xs) var(--mono);color:var(--ink3)}
.perr{margin:0;padding:var(--sp-2) var(--sp-3);border-radius:var(--r-md);
  background:var(--red-soft);color:var(--red);font-size:var(--fs-sm)}

.vbox{border:1px solid var(--line);border-radius:var(--r-md);padding:var(--sp-3);
  background:var(--sunken)}
.vh{margin:0 0 var(--sp-2);font-size:var(--fs-xs);color:var(--ink2)}
.vt{width:100%;font-size:var(--fs-xs)}
.vt th{text-align:left;color:var(--ink3);font-weight:600;padding:2px var(--sp-2) 2px 0}
.vt td{padding:2px var(--sp-2) 2px 0;color:var(--ink2);vertical-align:top}
.vt .mono{font:var(--fs-xs) var(--mono);color:var(--accent-deep);white-space:nowrap}

.pedit{min-height:320px;font:var(--fs-sm)/1.75 var(--mono);resize:vertical}
.pbar{display:flex;align-items:center;gap:var(--sp-3);flex-wrap:wrap}
.pbar .st{flex:1}
.bsel{width:auto;min-width:190px}
.nb{font-size:var(--fs-xs);color:var(--ink3)}
</style>

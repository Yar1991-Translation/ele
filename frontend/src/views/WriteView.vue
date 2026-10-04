<script setup>
/** 写作页：只放写作这一件事。
 *  顶部先告诉用户「素材就绪了吗」，不再等点了开始才报错。 */
import { reactive, ref, computed, watch, nextTick } from "vue";
import { useStore, api, runStage, toast, switchView } from "../store.js";
import { UiCard, UiField, UiSelect, UiSlider, UiBtn, UiBadge, UiEmpty } from "../ui";
import LogConsole from "../components/LogConsole.vue";

const s = useStore();

const form = reactive({
  mode: "auto", articleType: "CP向", cpCombo: "男男", ending: "不限",
  rating: "r12",
  personaSource: "both", officialWeight: 30, level: "配角",
  idea: "", draft: "", rosterAll: false,
});

const MODES = [
  { value: "auto", label: "自动生成", hint: "只写想法，从头生成一篇新文" },
  { value: "quick", label: "关键词速写", hint: "一个关键词+几张人物卡，AI 结合知识库设计剧情" },
  { value: "self", label: "我自己写", hint: "原稿原样收稿，不调用模型" },
  { value: "polish", label: "润色原稿", hint: "只改文笔，不动情节" },
  { value: "expand", label: "扩充原稿", hint: "以原稿情节为准，加细节扩写" },
  { value: "team", label: "团队润色", hint: "多位编辑讨论后改稿" },
];
const MODE_HINT = {
  auto: "想看什么？写得越具体越合口味。例：以失忆开篇、以死亡收尾，主角 @回响:主役",
  quick: "输入一个主题关键词即可，例：回忆、雨夜重逢、生日。也可以点上方人物卡点名；剧情走向由 AI 结合知识库设计，关键分歧会先问你",
  self: "（可选）标题或备注，原稿会原样收稿",
  polish: "（可选）润色的补充要求，例：对话再口语化一点",
  expand: "（可选）扩充的补充要求，例：多写心理活动，结尾慢一点",
  team: "（可选）团队润色的补充要求，例：文风再收敛一点",
};

const LEVELS = [
  { value: "跑龙套", label: "跑龙套（一两个镜头）" },
  { value: "微量", label: "微量（少量点缀）" },
  { value: "配角", label: "配角（有戏份不占主线）" },
  { value: "重要", label: "重要（关键配角）" },
  { value: "主役", label: "主役（核心主角）" },
];

const TYPE_OPTIONS = [{ value: "单人向", label: "单人向" }, { value: "CP向", label: "CP向" },
                      { value: "其他", label: "其他" }];
const CP_OPTIONS = ["微量", "男女", "男男", "女女", "多CP", "无CP"];
const ENDING_OPTIONS = [
  { value: "HE", label: "HE（好结局）" }, { value: "BE", label: "BE（坏结局）" },
  { value: "开放式", label: "开放式（不给结论）" }, { value: "不限", label: "不限" },
];
const RATING_OPTIONS = [
  { value: "r12", label: "R12（普遍级·全年龄）" },
  { value: "r16", label: "R16（辅导级）" },
  { value: "r18", label: "R18（无限制）" },
  { value: "r18g", label: "R18G（无限制·残酷描写）" },
];
const SOURCE_OPTIONS = [
  { value: "both", label: "两者结合" }, { value: "distilled", label: "仅蒸馏卡（同人形象）" },
  { value: "official", label: "仅官方卡（官方设定）" },
];

// 单人向锁微量
watch(() => form.articleType, t => { if (t === "单人向") form.cpCombo = "微量"; });

// config 回填默认值
watch(() => s.config, c => {
  const w = c?.write || {};
  if (w.mode) form.mode = w.mode;
  if (w.article_type) form.articleType = w.article_type;
  if (w.cp_combo) form.cpCombo = w.cp_combo;
  if (w.ending) form.ending = w.ending;
  if (w.rating) form.rating = w.rating;
  if (w.persona_source) form.personaSource = w.persona_source;
  if (w.official_weight !== undefined) form.officialWeight = w.official_weight;
}, { immediate: true, deep: true });

// 生成文章一键送入原稿框
watch(() => s.pendingDraft, pd => {
  if (!pd) return;
  form.mode = pd.mode || "team";
  form.draft = pd.content;
  if (form.articleType === "单人向") form.cpCombo = "微量";
  s.pendingDraft = null;
  toast("已载入「" + pd.name + "」到原稿框，确认后点开始");
}, { immediate: true });

// ---- @ 点名（与后端 pipeline/writer.py 保持一致，tests/test_gui_api.py 有契约测试）----
const MENTION_RE = /@([^\s@，。；！？、：:（）()【】\[\]「」『』'"”’]{1,30})(?:[:：]\s*([^\s@，。；！？、（）()【】\[\]]{1,6})|（\s*([^\s@，。；！？、：:（）()【】\[\]]{1,6})\s*）)?/g;
const ORDER = ["跑龙套", "微量", "配角", "重要", "主役"];

const mentions = computed(() => {
  const text = form.idea + "\n" + (form.mode === "auto" ? "" : form.draft);
  const order = [], levels = {};
  let m; MENTION_RE.lastIndex = 0;
  while ((m = MENTION_RE.exec(text)) !== null){
    const name = m[1], lv = (m[2] || m[3] || "").trim();
    if (!(name in levels)){ order.push(name); levels[name] = lv; }
    else if (lv){
      const prev = levels[name];
      if (!ORDER.includes(prev) || (ORDER.includes(lv) && ORDER.indexOf(lv) > ORDER.indexOf(prev)))
        levels[name] = lv;
    }
  }
  return order.map(n => ({ name: n, level: levels[n] || "配角" }));
});

const ideaRef = ref(null);
function insertMention(name){
  const el = ideaRef.value;
  const pos = el.selectionStart ?? form.idea.length;
  const end = el.selectionEnd ?? pos;
  const ins = "@" + name + ":" + form.level + " ";
  form.idea = form.idea.slice(0, pos) + ins + form.idea.slice(end);
  nextTick(() => { el.focus(); el.selectionStart = el.selectionEnd = pos + ins.length; });
}

const ideaChars = computed(() => form.idea.trim().length);

const promptFiles = computed(() =>
  (s.stats.output_groups?.prompt || s.stats.outputs || []).filter(n => n.includes("提示词")));

async function loadPromptFile(ev){
  const name = ev.target.value;
  ev.target.value = "";
  if (!name) return;
  try {
    const j = await api("/api/file/output/" + encodeURIComponent(name));
    form.idea = j.content;
    toast("已载入提示词，删掉用法说明后就能开写");
  } catch (e) { toast(String(e.message || e), true); }
}

// ---- 就绪检查 ----
const readiness = computed(() => {
  const out = [];
  const n = s.stats || {};
  if (!(n.posts > 0)) out.push("还没有任何素材——先到「素材」页跑一次爬取");
  else if (!(n.filtered > 0)) out.push("素材还没过滤——到「素材」页点「开始过滤」");
  else if (!(n.knowledge || []).length && !(n.charcards > 0))
    out.push("既没有知识库也没有人物卡——到「素材」页点「开始蒸馏」");
  return out;
});
const ready = computed(() => readiness.value.length === 0);

const lastDone = ref(null);
watch(() => s.stageResult, r => {
  if (r && r.stage === "write" && r.ok) lastDone.value = r;
});

async function startWrite(){
  const idea = form.idea.trim();
  const noDraft = form.mode === "auto" || form.mode === "quick";
  const draft = noDraft ? "" : form.draft.trim();
  if (noDraft && !idea) return toast("先写下你的想法再开始写作", true);
  if (!noDraft && !draft) return toast("先把原稿粘贴到下面的原稿框", true);
  lastDone.value = null;
  await runStage({
    stage: "write", idea, mode: form.mode, draft,
    roster_all: form.mode === "quick" ? form.rosterAll : false,
    article_type: form.articleType, cp_combo: form.cpCombo, ending: form.ending,
    rating: form.rating,
    persona_source: form.personaSource, official_weight: form.officialWeight,
  }).catch(e => toast(e.message, true));
}
</script>

<template>
  <div class="view">
    <!-- 就绪检查 -->
    <div v-if="!ready" class="ready warn">
      <b>还不能开写：</b>
      <span v-for="(t, i) in readiness" :key="t">{{ i ? "；" : "" }}{{ t }}</span>
      <UiBtn size="sm" @click="switchView('materials')">去素材页 →</UiBtn>
    </div>
    <div v-else class="ready ok">
      <b>素材已就绪</b><span>知识库 {{ (s.stats.knowledge || []).length }} 份 · 人物卡 {{ s.stats.charcards || 0 }} 张</span>
    </div>

    <UiCard title="写什么" desc="想法写得越具体，出来越合口味。用 @角色名 可以点名人物卡。">
      <div class="chips" v-if="s.personaNames.length">
        <span class="lb">人物卡</span>
        <button v-for="n in s.personaNames" :key="n" class="chip"
                :class="{ on: mentions.some(x => x.name === n) }"
                :title="'插入 @' + n + ':' + form.level"
                @click="insertMention(n)">
          @{{ n }}
          <em v-if="mentions.some(x => x.name === n)">
            · {{ mentions.find(x => x.name === n).level }}
          </em>
        </button>
      </div>

      <textarea ref="ideaRef" v-model="form.idea" class="idea"
                :placeholder="MODE_HINT[form.mode]"></textarea>

      <div class="ideabar">
        <span class="count" :class="{ over: ideaChars > 20000 }">{{ ideaChars }} 字</span>
        <label v-if="promptFiles.length" class="pick">
          <select @change="loadPromptFile">
            <option value="">载入提示词…</option>
            <option v-for="n in promptFiles" :key="n" :value="n">
              {{ n.replace(/^\d{8}-\d{6}_/, "").replace(/\.md$/, "") }}
            </option>
          </select>
        </label>
      </div>

      <label v-if="form.mode === 'quick'" class="roster-all">
        <input type="checkbox" v-model="form.rosterAll">
        全员登场（其余干员以跑龙套客串，仅限官方名单，已点名的角色不受影响）
      </label>

      <textarea v-if="form.mode !== 'auto' && form.mode !== 'quick'" v-model="form.draft" class="draft"
                placeholder="把你的原稿粘贴到这里"></textarea>
    </UiCard>

    <UiCard title="怎么写" desc="这些是本次生成用的；默认值可以在「设置」里改。">
      <div class="grid">
        <UiField label="写作方式" :help="(MODES.find(m => m.value === form.mode) || {}).hint">
          <UiSelect v-model="form.mode" :options="MODES" />
        </UiField>

        <UiField label="文章类型"
                 help="单人向＝只写一个人的视角，此时感情线自动锁成「微量」">
          <UiSelect v-model="form.articleType" :options="TYPE_OPTIONS" />
        </UiField>

        <UiField label="CP 组合" help="微量＝几乎不写感情线">
          <UiSelect v-model="form.cpCombo" :options="CP_OPTIONS"
                    :disabled="form.articleType === '单人向'" />
        </UiField>

        <UiField label="结局走向">
          <UiSelect v-model="form.ending" :options="ENDING_OPTIONS" />
        </UiField>

        <UiField label="内容分级"
                 help="生成内容的硬性边界，会注入全部生成与审校环节并标注在文首。R18/R18G 为无限制模式；涉及未成年人的性内容在任何模式下都禁止。">
          <UiSelect v-model="form.rating" :options="RATING_OPTIONS" />
        </UiField>

        <UiField label="人物卡来源"
                 help="官方卡＝官方设定（事实边界）；蒸馏卡＝同人语境里的形象">
          <UiSelect v-model="form.personaSource" :options="SOURCE_OPTIONS" />
        </UiField>

        <UiField label="点人物卡时用的出场比例">
          <UiSelect v-model="form.level" :options="LEVELS" />
        </UiField>

        <div v-if="form.personaSource === 'both'" class="span2">
          <UiField label="官方设定 vs 同人形象的权重"
                   help="数值越高越以官方设定为准。同人语境浓一点就调低。">
            <UiSlider v-model="form.officialWeight" :min="0" :max="100" :step="10" unit="%"
                      min-label="同人形象主导" max-label="官方设定主导" />
          </UiField>
        </div>
      </div>

      <div class="submit">
        <UiBtn variant="primary" :disabled="!!s.running || !ready" @click="startWrite">
          开始写作
        </UiBtn>
        <UiBtn v-if="lastDone" @click="switchView('library')">去看成果 →</UiBtn>
      </div>
    </UiCard>

    <LogConsole v-show="s.showLog || s.running || s.logs.length" />
  </div>
</template>

<style scoped>
.view{display:flex;flex-direction:column;gap:var(--sp-4)}
.ready{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;
  padding:var(--sp-3) var(--sp-4);border-radius:var(--r-md);font-size:var(--fs-sm)}
.ready.ok{background:var(--green-soft);color:var(--green)}
.ready.warn{background:var(--accent-soft);color:var(--accent-deep)}

.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:var(--sp-3)}
.chips .lb{font-size:var(--fs-xs);color:var(--ink3)}
.chip{padding:3px 12px;border-radius:var(--r-full);border:1px solid var(--line2);
  background:var(--surface);font-size:var(--fs-sm);transition:all var(--dur-fast)}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent);border-color:var(--accent);
  color:var(--on-accent);font-weight:600}
.chip em{font-style:normal;opacity:.85;font-weight:400}

textarea.idea{min-height:170px;resize:vertical;font-size:var(--fs-base)}
textarea.draft{min-height:170px;resize:vertical;margin-top:var(--sp-3)}
.ideabar{display:flex;align-items:center;justify-content:space-between;
  gap:var(--sp-3);margin-top:var(--sp-2)}
.roster-all{display:flex;align-items:center;gap:8px;font-size:var(--fs-sm);
  margin-top:var(--sp-2);cursor:pointer;color:var(--ink2)}
.roster-all input{width:auto}
.count{font:var(--fs-xs) var(--mono);color:var(--ink3)}
.count.over{color:var(--red)}
.pick select{width:auto;padding:3px 8px;font-size:var(--fs-xs)}

.grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-4)}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.span2{grid-column:1 / -1}
.submit{display:flex;gap:var(--sp-2);margin-top:var(--sp-5);align-items:center}
</style>

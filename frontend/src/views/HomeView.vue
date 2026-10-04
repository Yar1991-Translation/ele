<script setup>
/** 总览：一眼看清「我有多少素材、还差什么、上次写出了什么」。
 *  待办清单替代了以前让用户自己猜下一步的做法。 */
import { computed } from "vue";
import { useStore, switchView, toast } from "../store.js";
import { UiCard, UiBtn, UiBadge, UiEmpty } from "../ui";

const s = useStore();

const steps = computed(() => [
  { key: "crawl", label: "爬取", desc: "从 Lofter 抓文章",
    n: s.stats.posts || 0, unit: "篇", ok: (s.stats.posts || 0) > 0, go: "materials" },
  { key: "filter", label: "过滤", desc: "排除乙女向、图片帖、碎片帖",
    n: s.stats.filtered || 0, unit: "篇保留", ok: (s.stats.filtered || 0) > 0, go: "materials" },
  { key: "distill", label: "蒸馏", desc: "提炼成知识库",
    n: (s.stats.knowledge || []).length, unit: "份知识库", ok: (s.stats.knowledge || []).length > 0, go: "materials" },
  { key: "chars", label: "角色卡", desc: "从同人文提炼人物形象",
    n: s.stats.charcards || 0, unit: "张", ok: (s.stats.charcards || 0) > 0, go: "materials" },
]);

const todos = computed(() => {
  const out = [];
  const env = s.env || {};
  const cfg = s.config || {};
  if (!env.LOFTER_COOKIE?.set && !env.LOFTER_LOGIN_AUTH?.set)
    out.push({ text: "还没配置 Lofter 登录 Cookie", to: "settings" });
  if (!env.LLM_API_KEY?.set || !env.LLM_MODEL?.set)
    out.push({ text: "还没配置模型密钥或模型名", to: "settings" });
  if (!cfg.crawl?.tag) out.push({ text: "还没填要爬的标签名", to: "settings" });
  if (!(s.stats.posts > 0)) out.push({ text: "还没有任何素材，先跑一次爬取", to: "materials" });
  else if (!(s.stats.filtered > 0)) out.push({ text: "素材还没过滤，写出来会不干净", to: "materials" });
  else if (!(s.stats.knowledge || []).length) out.push({ text: "还没蒸馏知识库，写作缺少参照", to: "materials" });
  return out;
});

const latest = computed(() => {
  const g = s.stats.output_groups?.article || [];
  return g[0] || null;
});

const lastLog = computed(() => (s.logs || []).slice(-6));
</script>

<template>
  <div class="view">
    <header class="hero">
      <div>
        <h1>蒸馏工坊</h1>
        <p>爬同人文 → 过滤 → 蒸馏成知识库 → 按你的想法写一篇。</p>
      </div>
      <div class="hero-act">
        <UiBtn variant="primary" @click="switchView('write')">去写一篇</UiBtn>
        <UiBtn @click="switchView('materials')">准备素材</UiBtn>
        <UiBtn ghost @click="s.wizard = true">设置向导</UiBtn>
      </div>
    </header>

    <!-- 待办 -->
    <UiCard v-if="todos.length" title="开始之前还差这几步"
            desc="按顺序做，做完就能写。">
      <ol class="todos">
        <li v-for="(t, i) in todos" :key="t.text">
          <span class="n">{{ i + 1 }}</span>
          <span class="txt">{{ t.text }}</span>
          <UiBtn size="sm" ghost @click="switchView(t.to)">去处理 →</UiBtn>
        </li>
      </ol>
    </UiCard>

    <!-- 素材就绪度 -->
    <UiCard title="素材就绪度" desc="四个阶段的产物。绿色表示这一步已经有东西了。">
      <div class="steps">
        <button v-for="st in steps" :key="st.key" class="step" :class="{ ok: st.ok }"
                @click="switchView(st.go)">
          <span class="mark" aria-hidden="true">{{ st.ok ? "✓" : "○" }}</span>
          <b>{{ st.label }}</b>
          <em>{{ st.n }} {{ st.unit }}</em>
          <span class="d">{{ st.desc }}</span>
        </button>
      </div>
    </UiCard>

    <div class="row2">
      <!-- 上次成果 -->
      <UiCard title="最近写出来的" desc="点开可以直接读。">
        <UiEmpty v-if="!latest" title="还没有生成过文章"
                 hint="素材准备好后，到「写作」页写下你的想法。"
                 icon="✎">
          <UiBtn variant="primary" @click="switchView('write')">去写一篇</UiBtn>
        </UiEmpty>
        <div v-else class="latest">
          <span class="fn">{{ latest.replace(/^\d{8}-\d{6}_/, "").replace(/\.md$/, "") }}</span>
          <span class="meta">{{ latest.slice(0, 8) }} · 共 {{ (s.stats.output_groups?.article || []).length }} 篇</span>
          <UiBtn size="sm" @click="switchView('library')">去成果库 →</UiBtn>
        </div>
      </UiCard>

      <!-- 最近日志 -->
      <UiCard title="最近记录" desc="后台在做什么，一眼看到。">
        <UiEmpty v-if="!lastLog.length" title="还没有运行记录"
                 hint="跑过任何阶段后，这里会留下痕迹。" icon="▤" />
        <div v-else class="logs">
          <div v-for="e in lastLog" :key="e.i" class="lg">
            <span class="t">{{ e.t }}</span><span class="x">{{ e.text }}</span>
          </div>
        </div>
      </UiCard>
    </div>

    <p class="foot">
      提示：改完设置要点「保存」；生成过程中可以随时切页面，底部任务条会一直显示进度。
    </p>
  </div>
</template>

<style scoped>
.view{display:flex;flex-direction:column;gap:var(--sp-4)}
.hero{display:flex;align-items:flex-end;justify-content:space-between;
  gap:var(--sp-4);padding:var(--sp-2) var(--sp-1)}
.hero h1{font-size:var(--fs-2xl);letter-spacing:2px}
.hero p{margin-top:6px;color:var(--ink2);font-size:var(--fs-md)}
.hero-act{display:flex;gap:var(--sp-2);flex:none}

.todos{margin:0;padding-left:0;list-style:none;display:flex;flex-direction:column;gap:var(--sp-2)}
.todos li{display:flex;align-items:center;gap:var(--sp-3);
  padding:var(--sp-2) var(--sp-3);border-radius:var(--r-md);background:var(--sunken)}
.todos .n{flex:none;width:20px;height:20px;border-radius:50%;background:var(--accent);
  color:var(--on-accent);font-size:var(--fs-xs);font-weight:700;
  display:flex;align-items:center;justify-content:center}
.todos .txt{flex:1;font-size:var(--fs-base)}

.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--sp-3)}
.step{display:flex;flex-direction:column;gap:3px;text-align:left;
  padding:var(--sp-3) var(--sp-4);border:1px solid var(--line2);
  border-radius:var(--r-md);background:var(--surface)}
.step:hover{border-color:var(--accent);background:var(--hover)}
.step.ok{border-color:var(--green)}
.step .mark{font-size:15px;color:var(--ink3)}
.step.ok .mark{color:var(--green)}
.step b{font-size:var(--fs-md)}
.step em{font-style:normal;font:600 var(--fs-sm) var(--mono);color:var(--accent-deep)}
.step .d{font-size:var(--fs-xs);color:var(--ink3)}

.row2{display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-4)}
@media(max-width:900px){.row2{grid-template-columns:1fr}}
.latest{display:flex;flex-direction:column;gap:var(--sp-2);align-items:flex-start}
.fn{font-size:var(--fs-md);font-weight:600}
.meta{font-size:var(--fs-sm);color:var(--ink3)}
.logs{display:flex;flex-direction:column;gap:5px;font:var(--fs-xs)/1.7 var(--mono)}
.lg{display:flex;gap:var(--sp-2);overflow:hidden}
.lg .t{color:var(--ink3);flex:none}
.lg .x{color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.foot{font-size:var(--fs-sm);color:var(--ink3);margin-top:var(--sp-1)}
</style>

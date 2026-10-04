<script setup>
/** 底部常驻任务条：任何页面都能看到当前阶段、进度、耗时、失败原因。
 *  日志框以前只在运行页，切到设置页就看不见正在跑什么了。
 *  写作过程中 LLM 的提问也在这里回答——进程会暂停等你。 */
import { computed, reactive, ref, watch } from "vue";
import { useStore, stopStage, answerQuestion, toast } from "../store.js";
import { UiProgress, UiBtn, UiBadge } from "../ui";

const s = useStore();

// ---- 提问面板 ----
const draft = reactive([]);      // 每题的自由输入；点了选项 chip 也写进来
const answering = ref(false);

watch(() => s.question?.id, () => { draft.length = 0; });

function pick(i, opt){ draft[i] = opt; }

async function submit(skip){
  const q = s.question;
  if (!q) return;
  answering.value = true;
  try {
    const answers = {};
    (q.items || []).forEach((it, i) => {
      answers[String(i)] = (draft[i] || "").trim() || (it.suggest || "");
    });
    await answerQuestion(q.id, answers, skip);
  } catch (e) { toast(String(e.message || e), true); }
  answering.value = false;
}

const STAGE_LABEL = {
  crawl: "爬取", filter: "过滤", distill: "蒸馏", chars: "角色卡",
  write: "写作", runall: "一键跑素材", selftest: "自测",
};

const pct = computed(() => {
  const p = s.progress;
  return p && p.total ? Math.round(p.cur / p.total * 100) : 0;
});

const elapsedText = computed(() => {
  const e = s.elapsed;
  if (!e && e !== 0) return "";
  return e < 60 ? e + " 秒" : Math.floor(e / 60) + " 分 " + (e % 60) + " 秒";
});

// 剩余时间估算：按已完成部分的平均速度线性外推，仅供毛估
const etaText = computed(() => {
  const p = s.progress, e = s.elapsed;
  if (!p || !p.total || !p.cur || !e || e < 5) return "";
  const left = Math.round(e / p.cur * (p.total - p.cur));
  if (!left || left < 3) return "";
  return left < 60 ? "剩约 " + left + " 秒"
                   : "剩约 " + Math.floor(left / 60) + " 分 " + (left % 60) + " 秒";
});

const failed = computed(() => s.stageResult && !s.stageResult.ok ? s.stageResult : null);
</script>

<template>
  <div class="taskbar" :class="{ running: s.running, failed, asking: !!s.question }">
    <!-- 写作提问：进程暂停中，回答后继续 -->
    <div v-if="s.question" class="ask">
      <div class="ask-hd">
        <b>💬 {{ s.question.title || "写作想确认" }}</b>
        <span class="ask-sub">回答后继续写；不回答的话，超时按建议继续</span>
      </div>
      <div v-for="(it, i) in s.question.items || []" :key="i" class="ask-item">
        <p class="ask-q">{{ i + 1 }}. {{ it.q }}</p>
        <div class="ask-opts">
          <button v-for="o in it.options || []" :key="o" class="achip"
                  :class="{ on: draft[i] === o }" @click="pick(i, o)">{{ o }}</button>
          <input v-model="draft[i]" type="text" class="ain"
                 :placeholder="it.suggest ? '补充或其他（默认：' + it.suggest + '）' : '你的回答'"
                 @keyup.enter="submit(false)">
        </div>
      </div>
      <div class="ask-acts">
        <UiBtn variant="primary" size="sm" :loading="answering" @click="submit(false)">
          回答并继续
        </UiBtn>
        <UiBtn size="sm" ghost @click="submit(true)">跳过，按建议继续</UiBtn>
      </div>
    </div>

    <template v-else-if="s.running">
      <span class="dot" aria-hidden="true"></span>
      <span class="name">正在{{ STAGE_LABEL[s.running] || s.running }}</span>
      <UiProgress class="bar" :label="s.progress ? `${s.progress.label} ${s.progress.cur}/${s.progress.total}` : ''"
                  :percent="pct" :indeterminate="!s.progress" />
      <span v-if="elapsedText" class="elapsed">已 {{ elapsedText }}</span>
      <span v-if="etaText" class="elapsed eta">{{ etaText }}</span>
      <UiBtn variant="stop" size="sm" @click="stopStage().catch(e => toast(e.message, true))">停止</UiBtn>
    </template>

    <template v-else-if="failed">
      <UiBadge tone="red">失败</UiBadge>
      <span class="name">{{ STAGE_LABEL[failed.stage] || failed.stage }}没能跑完</span>
      <span class="reason">{{ failed.error_summary || ("退出码 " + failed.exit_code) }}</span>
      <UiBtn size="sm" ghost @click="s.showLog = true">看日志</UiBtn>
    </template>

    <template v-else>
      <span class="idle">空闲</span>
      <span class="reason">素材准备好后，到「素材」页跑爬取 → 过滤 → 蒸馏</span>
    </template>
  </div>
</template>

<style scoped>
.taskbar{position:sticky;bottom:0;z-index:var(--z-sticky);
  display:flex;align-items:center;gap:var(--sp-3);
  margin-top:var(--sp-5);padding:var(--sp-2) var(--sp-4);
  background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-lg);box-shadow:var(--shadow)}
.taskbar.running{border-color:var(--accent)}
.taskbar.failed{border-color:var(--red);background:var(--red-soft)}
.taskbar.asking{flex-direction:column;align-items:stretch;
  border-color:var(--accent);background:var(--accent-soft)}

/* ---- 提问面板 ---- */
.ask{display:flex;flex-direction:column;gap:var(--sp-2)}
.ask-hd{display:flex;align-items:baseline;gap:var(--sp-3);flex-wrap:wrap}
.ask-hd b{font-size:var(--fs-base)}
.ask-sub{font-size:var(--fs-xs);color:var(--ink3)}
.ask-item{display:flex;flex-direction:column;gap:5px}
.ask-q{margin:0;font-size:var(--fs-sm);font-weight:600}
.ask-opts{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.achip{padding:3px 12px;border-radius:var(--r-full);border:1px solid var(--line2);
  background:var(--surface);font-size:var(--fs-sm);transition:all var(--dur-fast)}
.achip:hover{border-color:var(--accent)}
.achip.on{background:var(--accent);border-color:var(--accent);
  color:var(--on-accent);font-weight:600}
.ain{width:auto;min-width:200px;flex:1;padding:4px 10px;font-size:var(--fs-sm)}
.ask-acts{display:flex;align-items:center;gap:var(--sp-2);margin-top:2px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--accent);flex:none;
  animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}
.name{font-size:var(--fs-sm);font-weight:600;white-space:nowrap}
.bar{flex:1;min-width:120px}
.elapsed{font:var(--fs-xs) var(--mono);color:var(--ink3);white-space:nowrap}
.elapsed.eta{color:var(--accent-deep)}
.reason{font-size:var(--fs-sm);color:var(--ink2);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;flex:1}
.idle{font-size:var(--fs-sm);color:var(--ink3);white-space:nowrap}
</style>

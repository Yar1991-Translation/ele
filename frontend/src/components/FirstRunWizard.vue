<script setup>
/** 首启向导：没配登录 / 没填 tag / 没素材时弹出（手动也可从总览打开）。
 *  四步走：① 验证登录 → ② 测试模型 → ③ 选 tag + 预设 → ④ 跑一次小样例。
 *  每步都「先保存再验证」，一步做不完随时可跳过，向导只在首次自动弹。 */
import { computed, reactive, ref, watch, onMounted } from "vue";
import { useStore, api, saveEnv, saveConfig, runStage, toast } from "../store.js";
import { UiDialog, UiBtn, UiField, UiBadge } from "../ui";

const s = useStore();
const KEY = "distiller-wizard-done";      // 关掉过就不再自动弹

const open = ref(false);
const step = ref(1);
const busy = ref("");
const results = reactive({ lofter: null, llm: null });   // {ok, note}
const presets = ref([]);
const pick = ref("trial");

const form = reactive({ cookie: "", loginKey: "", loginAuth: "",
                        baseUrl: "", apiKey: "", model: "", tag: "" });

const need = computed(() => {
  const env = s.env || {};
  const noCookie = !env.LOFTER_COOKIE?.set && !env.LOFTER_LOGIN_AUTH?.set;
  const noTag = !(s.config?.crawl?.tag || "").trim();
  const noMaterial = !(s.stats?.posts > 0);
  return { noCookie, noTag, noMaterial, any: noCookie || noTag || noMaterial };
});

const STEPS = [
  { n: 1, label: "验证登录" }, { n: 2, label: "测试模型" },
  { n: 3, label: "选标签与预设" }, { n: 4, label: "跑小样例" },
];

function fillFromState(){
  const c = s.config || {}, env = s.env || {};
  form.tag = c.crawl?.tag || "";
  form.baseUrl = env.LLM_BASE_URL?.value || "";
  form.model = env.LLM_MODEL?.value || "";
  // 密文不回显，留空 = 保持不变
  form.cookie = ""; form.apiKey = ""; form.loginKey = ""; form.loginAuth = "";
}

function maybeOpen(){
  if (open.value) return;
  if (s.wizard || (!localStorage.getItem(KEY) && need.value.any)){
    fillFromState();
    // 缺哪步就从哪步开始
    step.value = need.value.noCookie ? 1
               : (!s.env?.LLM_API_KEY?.set || !s.env?.LLM_MODEL?.set ? 2 : 3);
    open.value = true;
    if (!presets.value.length) loadPresets();
  }
}

async function loadPresets(){
  try {
    const j = await api("/api/config-schema");
    presets.value = j.presets || [];
  } catch { /* 向导容错：拿不到就只手填 tag */ }
}

async function verify(kind){
  busy.value = kind;
  try {
    // 验证接口读 .env 文件：先把手上的内容落盘
    const patch = {};
    if (kind === "lofter"){
      if (form.cookie) patch.LOFTER_COOKIE = form.cookie;
      if (form.loginKey) patch.LOFTER_LOGIN_KEY = form.loginKey;
      if (form.loginAuth) patch.LOFTER_LOGIN_AUTH = form.loginAuth;
    } else {
      if (form.baseUrl) patch.LLM_BASE_URL = form.baseUrl;
      if (form.apiKey) patch.LLM_API_KEY = form.apiKey;
      if (form.model) patch.LLM_MODEL = form.model;
    }
    if (Object.keys(patch).length){
      await saveEnv(patch);
      if (kind === "lofter"){ form.cookie = ""; form.loginKey = ""; form.loginAuth = ""; }
      else form.apiKey = "";
    }
    const r = await api("/api/verify/" + kind, { method: "POST" });
    results[kind] = r;
    toast(r.note, !r.ok);
    if (r.ok) await refreshEnvView();
  } catch (e) { toast(String(e.message || e), true); }
  busy.value = "";
}

async function refreshEnvView(){
  try { const st = await api("/api/state"); s.env = st.env; s.config = st.config; } catch { /* 忽略 */ }
}

const presetObj = computed(() => presets.value.find(p => p.key === pick.value));

function goNext(){
  if (step.value === 3 && !form.tag.trim()){
    return toast("先填要爬的标签名（Lofter 话题标签，直接写中文）", true);
  }
  if (step.value < 4){ step.value++; return; }
  finish(true);
}

function finish(run){
  open.value = false;
  s.wizard = false;
  localStorage.setItem(KEY, "1");
  if (run) startSample();
}

async function startSample(){
  try {
    // 小样例统一先爬 20 篇：就算套了「标准」预设也不会一口气爬爆
    const values = { ...(presetObj.value?.values || {}) };
    values["crawl.tag"] = form.tag.trim();
    values["crawl.max_count"] = 20;
    await saveConfig(values);
    toast("向导已保存设置，开始爬 20 篇小样例——进度看底部任务条");
    await runStage({ stage: "crawl" });
  } catch (e) { toast(String(e.message || e), true); }
}

watch(() => s.wizard, v => { if (v) maybeOpen(); });
onMounted(() => { loadPresets(); maybeOpen(); });
// 初始 state 是异步到的（env/config/stats），到齐后再判一次
watch(() => [s.env, s.stats, s.config], () => { if (!open.value) maybeOpen(); }, { deep: true });
</script>

<template>
  <UiDialog :open="open" title="欢迎使用蒸馏工坊"
            desc="四步配好就能跑：登录 → 模型 → 标签 → 小样例。每步都可以跳过，之后在「设置」里补。"
            width="620px" @close="finish(false)">
    <!-- 步骤条 -->
    <ol class="steps">
      <li v-for="st in STEPS" :key="st.n" :class="{ on: step === st.n, done: step > st.n }">
        <span class="n">{{ step > st.n ? "✓" : st.n }}</span>
        <span class="lb">{{ st.label }}</span>
      </li>
    </ol>

    <!-- ① 登录 -->
    <section v-if="step === 1" class="body">
      <p class="lead">爬文章需要 Lofter 的登录态。浏览器 F12 → 应用 → Cookie，
        复制 <b>LOFTER_SESS</b> 的值（或整行 Cookie）粘到下面。</p>
      <UiField label="Lofter Cookie" help="只填值也行，整行 Cookie 也认。保密项不会回显。">
        <input v-model="form.cookie" type="password" placeholder="粘贴 Cookie 值">
      </UiField>
      <div class="vrow">
        <UiBtn :loading="busy === 'lofter'" variant="primary" @click="verify('lofter')">
          保存并验证登录
        </UiBtn>
        <UiBadge v-if="results.lofter" :tone="results.lofter.ok ? 'green' : 'red'">
          {{ results.lofter.ok ? "登录有效" : "没通过" }}
        </UiBadge>
      </div>
      <p v-if="results.lofter && !results.lofter.ok" class="warn">{{ results.lofter.note }}</p>
    </section>

    <!-- ② 模型 -->
    <section v-else-if="step === 2" class="body">
      <p class="lead">写作和蒸馏要用大模型。火山方舟（豆包）、DeepSeek、Kimi 等都行，
        只要接口是 OpenAI 兼容的。</p>
      <UiField label="接口地址" help="例如 https://ark.example.com/api/v3">
        <input v-model="form.baseUrl" type="text" placeholder="LLM_BASE_URL">
      </UiField>
      <UiField label="API Key" help="保密项不会回显；不填 = 沿用现有的。">
        <input v-model="form.apiKey" type="password" placeholder="LLM_API_KEY">
      </UiField>
      <UiField label="主模型" help="模型名或接入点 ID，例如 doubao-xxx">
        <input v-model="form.model" type="text" placeholder="LLM_MODEL">
      </UiField>
      <div class="vrow">
        <UiBtn :loading="busy === 'llm'" variant="primary" @click="verify('llm')">
          保存并测试模型
        </UiBtn>
        <UiBadge v-if="results.llm" :tone="results.llm.ok ? 'green' : 'red'">
          {{ results.llm.ok ? "已连通" : "没通过" }}
        </UiBadge>
      </div>
      <p v-if="results.llm && !results.llm.ok" class="warn">{{ results.llm.note }}</p>
    </section>

    <!-- ③ tag + 预设 -->
    <section v-else-if="step === 3" class="body">
      <p class="lead">告诉工坊要爬哪个标签，再选个用量档位（之后随时能改）。</p>
      <UiField label="Lofter 标签名" help="直接写中文，例如「洲回响」" required>
        <input v-model="form.tag" type="text" placeholder="洲回响"
               @keyup.enter="goNext">
      </UiField>
      <div class="presets">
        <button v-for="p in presets" :key="p.key" class="preset"
                :class="{ on: pick === p.key }" @click="pick = p.key">
          <b>{{ p.label }}</b>
          <span>{{ p.desc }}</span>
        </button>
      </div>
    </section>

    <!-- ④ 小样例 -->
    <section v-else class="body">
      <p class="lead">万事俱备。点下面的按钮就开跑——先爬 <b>20 篇</b>小样例，
        确认没问题后到「设置」套「标准」预设放开。</p>
      <ul class="sum">
        <li><span>标签</span><b>{{ form.tag || "（未填）" }}</b></li>
        <li><span>登录</span><b>{{ results.lofter?.ok ? "已验证" : "没验证（也能跑，爬不到再来查）" }}</b></li>
        <li><span>模型</span><b>{{ results.llm?.ok ? "已连通" : "没测（过滤/蒸馏/写作要用）" }}</b></li>
        <li><span>档位</span><b>{{ presetObj?.label || "试跑 20 篇（省钱）" }}</b></li>
      </ul>
    </section>

    <template #footer>
      <UiBtn ghost @click="finish(false)">跳过向导</UiBtn>
      <UiBtn v-if="step > 1" @click="step--">上一步</UiBtn>
      <UiBtn v-if="step < 4" variant="primary" @click="goNext">下一步</UiBtn>
      <UiBtn v-else variant="primary" :loading="!!busy" @click="finish(true)">
        开始小样例（爬 20 篇）
      </UiBtn>
    </template>
  </UiDialog>
</template>

<style scoped>
.steps{display:flex;gap:var(--sp-1);margin:0 0 var(--sp-4);padding:0;list-style:none}
.steps li{flex:1;display:flex;align-items:center;gap:6px;padding:var(--sp-2);
  border-radius:var(--r-md);background:var(--sunken);font-size:var(--fs-xs);color:var(--ink3)}
.steps li.on{background:var(--accent-soft);color:var(--accent-deep);font-weight:600}
.steps li.done{color:var(--green)}
.steps .n{flex:none;width:18px;height:18px;border-radius:50%;background:var(--surface);
  border:1px solid var(--line2);display:flex;align-items:center;justify-content:center;
  font-size:10px}
.steps li.on .n{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.steps li.done .n{background:var(--green);border-color:var(--green);color:#fff}
.steps .lb{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.body{display:flex;flex-direction:column;gap:var(--sp-3)}
.lead{margin:0;font-size:var(--fs-sm);line-height:1.75;color:var(--ink2)}
.vrow{display:flex;align-items:center;gap:var(--sp-3)}
.warn{margin:0;padding:var(--sp-2) var(--sp-3);border-radius:var(--r-md);
  background:var(--red-soft);color:var(--red);font-size:var(--fs-sm)}

.presets{display:grid;grid-template-columns:1fr;gap:var(--sp-2)}
.preset{display:flex;flex-direction:column;gap:2px;text-align:left;
  padding:var(--sp-2) var(--sp-3);border:1px solid var(--line2);
  border-radius:var(--r-md);background:var(--surface)}
.preset:hover{border-color:var(--accent)}
.preset.on{border-color:var(--accent);background:var(--accent-soft)}
.preset b{font-size:var(--fs-sm)}
.preset span{font-size:var(--fs-xs);color:var(--ink3);line-height:1.6}

.sum{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:var(--sp-2)}
.sum li{display:flex;justify-content:space-between;gap:var(--sp-3);
  padding:var(--sp-2) var(--sp-3);border-radius:var(--r-md);background:var(--sunken);
  font-size:var(--fs-sm)}
.sum li span{color:var(--ink3)}
.sum li b{font-weight:600;text-align:right}
</style>

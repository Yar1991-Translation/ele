/** 全局状态与 API：单例 reactive store，App 挂载时 init()。 */
import { reactive } from "vue";

export const FRONTEND_VERSION = "20261005.16";

const state = reactive({
  view: "home",                  // home | materials | write | library | settings
  running: null,                 // 当前运行阶段 key 或 null
  exitCode: null,
  elapsed: null,                 // 当前阶段已运行秒数
  stageResult: null,             // 最近一次结束的阶段 {stage, ok, exit_code, error_summary}
  showLog: false,                // 任务条要求展开日志
  logs: [],                    // {i, t, text}
  lastLog: -1,
  stats: { posts: 0, filtered: 0, excluded: 0, distilled: 0,
           knowledge: [], outputs: [], types: {} },
  config: {},
  env: {},
  toast: null,                 // {msg, err}
  reader: null,                // 阅读器：{title, subtitle, html, url}
  compare: null,               // 两篇对比：{left:{name,content}, right:{name,content}}
  question: null,              // 写作提问：{id,title,items:[{q,options,suggest}],expires_at}
  pendingDraft: null,          // 待填入原稿框的生成文章
  wizard: false,               // 手动打开首启向导（自动弹出另有触发条件）
  personaNames: [],            // 人物卡名字（去重，供 chips）
  server_version: "",
  progress: null,              // {label, cur, total}｜null，由日志里的进度行驱动
});

let toastTimer = null;
let prevRunning = undefined;
let pollTick = 0;
let pollTimer = null;
let offlineTicks = 0;      // 连续失联次数：别让界面永远挂着「运行中」

export function useStore(){ return state; }

export function toast(msg, err){
  state.toast = { msg, err: !!err };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { state.toast = null; }, 4200);
}

export async function api(path, opts){
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ error: r.statusText }));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

export const jsonBody = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(body) });

// ---------------- 动作 ----------------
export async function loadState(){
  const st = await api("/api/state");
  if (st.server_version && st.server_version !== FRONTEND_VERSION){
    // 版本不一致：先自动重载一次（旧标签页场景，重载即拿到新界面）；
    // 重载后仍不一致说明后端进程是旧的，才提示重启
    if (!sessionStorage.getItem("verReloaded")){
      sessionStorage.setItem("verReloaded", "1");
      toast("界面已自动更新，正在刷新…");
      setTimeout(() => location.reload(), 900);
      return;
    }
    toast("后端是旧版本且刷新无效：请关掉 GUI 重新运行 python gui.py", true);
  } else {
    sessionStorage.removeItem("verReloaded");
  }
  state.config = st.config;
  state.env = st.env;
  state.stats = st.stats;
  state.server_version = st.server_version;
}

export async function refreshData(){
  state.stats = await api("/api/data");
  return state.stats;
}

export async function runStage(payload){
  await api("/api/run", jsonBody(payload));
  poll();
}

export async function stopStage(){
  await api("/api/stop", { method: "POST" });
  toast("已发送停止信号");
}

export async function saveConfig(patch){
  const r = await api("/api/config", jsonBody(patch));
  toast("已保存：" + r.changed.join("、"));
  await refreshData();
  return r;
}

export async function saveEnv(patch){
  const r = await api("/api/env", jsonBody(patch));
  toast(r.changed.length ? "已保存：" + r.changed.join("、") : "没有需要保存的修改");
  return r;
}

export async function loadPersonas(){
  const j = await api("/api/personas");
  state.personaNames = [...new Set(j.files.flatMap(f => f.names))];
  return j;
}

export async function uploadPersonas(files){
  const fd = new FormData();
  [...files].forEach(f => fd.append("files", f));
  const r = await fetch("/api/personas", { method: "POST", body: fd });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  toast("已导入：" + j.saved.join("、"));
  await loadPersonas();
  return j;
}

export async function deletePersona(file){
  await api("/api/personas/" + encodeURIComponent(file), { method: "DELETE" });
  toast("已删除");
  await loadPersonas();
}

export function switchView(v){ state.view = v; }

// 把生成文章一键送入团队润色：拉取内容 -> 切到运行页 -> 填入原稿框
export async function draftFromOutput(name, mode){
  const j = await api("/api/file/output/" + name);
  state.pendingDraft = { name, content: j.content, mode: mode || "team" };
  state.view = "write";
}

// ---------------- 阅读器 ----------------
export function openReader(payload){ state.reader = payload; }
export function closeReader(){ state.reader = null; }

// ---------------- 写作提问 ----------------
export async function answerQuestion(id, answers, skip){
  await api("/api/answer", jsonBody({ id, answers: answers || {}, skip: !!skip }));
  state.question = null;
  toast(skip ? "已跳过提问，按建议继续写作" : "已回答，写作继续");
}

// ---------------- 两篇对比 ----------------
export async function openCompare(nameA, nameB){
  const [a, b] = await Promise.all([
    api("/api/file/output/" + encodeURIComponent(nameA)),
    api("/api/file/output/" + encodeURIComponent(nameB)),
  ]);
  state.compare = {
    left: { name: nameA, content: a.content },
    right: { name: nameB, content: b.content },
  };
}
export function closeCompare(){ state.compare = null; }
export async function openPost(url){
  state.reader = { title: "加载中…", subtitle: "", md: "", url };
  try {
    const j = await api("/api/post-content?url=" + encodeURIComponent(url));
    state.reader = {
      title: j.title,
      subtitle: [j.author, j.publish_time, (j.tags || []).join("、")].filter(Boolean).join(" · "),
      md: j.content,
      url,
    };
  } catch(e){
    state.reader = { title: "加载失败", subtitle: String(e.message || e), md: "", url };
  }
}

// ---------------- 轮询 ----------------
// 进度行：后端打印 `# 进度：章节 2/5`；另外兼容各阶段已有的 `[12/39]` 进度格式
const PROG_MARK = /^#\s*进度：(\S+)\s+(\d+)\/(\d+)/;
const PROG_BRACKET = /\[(\d+)\/(\d+)\]/;
const STAGE_LABEL = { crawl: "爬取", filter: "判定", distill: "蒸馏",
                      chars: "角色卡", write: "写作" };

export function isProgressLine(text){ return PROG_MARK.test(text || ""); }

function appendLog(e){
  const m = PROG_MARK.exec(e.text || "");
  if (m){
    state.progress = { label: m[1], cur: +m[2], total: +m[3] };
    return;                      // 机器标记不进日志
  }
  const b = PROG_BRACKET.exec(e.text || "");
  if (b) state.progress = { label: STAGE_LABEL[state.running] || "进行中",
                            cur: +b[1], total: +b[2] };
  state.logs.push(e);
  if (state.logs.length > 3000) state.logs.shift();
}

let lastBuild = null;   // 构建指纹：变化即前端有更新

async function poll(){
  try {
    const j = await api("/api/logs?since=" + state.lastLog);
    if (j.build){
      if (lastBuild === null) lastBuild = j.build;
      else if (j.build !== lastBuild){
        lastBuild = j.build;
        toast("检测到界面更新，正在刷新页面…");
        setTimeout(() => location.reload(), 900);
        return;
      }
    }
    state.lastLog = j.last;
    j.lines.forEach(appendLog);
    state.running = j.running;
    state.exitCode = j.exit_code;
    state.elapsed = j.elapsed ?? null;
    if (j.stage_result) state.stageResult = j.stage_result;
    if ("question" in j) state.question = j.question || null;
    if (!j.running) state.progress = null;   // 阶段结束清掉进度条
    if (prevRunning && !j.running) refreshData().catch(() => {});
    prevRunning = j.running;
    if (++pollTick % 6 === 0 && !j.running) refreshData().catch(() => {});
  } catch (e) {
    // 服务不可达：别让界面永远挂着「运行中」
    if (++offlineTicks >= 3 && state.running){
      state.running = null;
      state.progress = null;
      toast("连不上本地服务了：请关掉后重新运行 python gui.py", true);
    }
    if (!state.running) offlineTicks = 0;
  }
}

export function init(){
  if (typeof window !== "undefined") window.__store = state;   // 调试句柄
  loadState().catch(() => {});
  loadPersonas().catch(() => {});
  refreshData().catch(() => {});
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(poll, 1200);
  poll();
}

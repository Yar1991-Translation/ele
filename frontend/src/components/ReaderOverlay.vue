<script setup>
/** 全屏阅读器：role=dialog、ESC 关闭、字号可调（记忆）、阅读进度记忆，支持 md 或 html 正文。 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useStore, closeReader } from "../store.js";
import { mdToHtml } from "../md.js";
import { UiBtn, UiBadge } from "../ui";

const s = useStore();
const SIZE_KEY = "distiller-reader-size";
const size = ref(Number(localStorage.getItem(SIZE_KEY) || 17));
watch(size, v => localStorage.setItem(SIZE_KEY, String(v)));

const body = computed(() => {
  const r = s.reader;
  if (!r) return "";
  return r.html != null ? r.html : mdToHtml(r.md || "");
});

// 目录：从正文标题抽出来，长文跳着看
const toc = computed(() => {
  const r = s.reader;
  const md = r?.md || "";
  return [...md.matchAll(/^(#{2,3})\s+(.+)$/gm)].map(m => ({
    level: m[1].length, text: m[2].trim(), id: "h-" + m[2].trim().slice(0, 20),
  }));
});

// 阅读进度记忆：按文件记滚动位置，下次打开接着读
const POS_KEY = "distiller-reader-pos";
const box = ref(null);
function posKey(){
  const r = s.reader;
  return r ? (r.file || r.url || r.title || "") : "";
}
function savePos(){
  const k = posKey();
  if (!k || !box.value) return;
  try {
    const m = JSON.parse(localStorage.getItem(POS_KEY) || "{}");
    m[k] = box.value.scrollTop;
    // 只留最近 50 个位置，别把存储撑爆
    const keys = Object.keys(m);
    if (keys.length > 50) delete m[keys[0]];
    localStorage.setItem(POS_KEY, JSON.stringify(m));
  } catch { /* 隐私模式下写不了就不管 */ }
}
function restorePos(){
  const k = posKey();
  if (!k || !box.value) return;
  try {
    const m = JSON.parse(localStorage.getItem(POS_KEY) || "{}");
    box.value.scrollTop = m[k] || 0;
  } catch { /* 同上 */ }
}

let posTimer = null;
function onScroll(){
  if (posTimer) return;
  posTimer = setTimeout(() => { posTimer = null; savePos(); }, 400);
}

// 打开（或换内容）后回到上次读到的位置
watch(() => s.reader, () => { nextTick(restorePos); }, { deep: true });

function onKey(e){ if (e.key === "Escape") closeReader(); }
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <transition name="reader">
      <div v-if="s.reader" ref="box" class="overlay" @click.self="closeReader()"
           @scroll.passive="onScroll">
        <article class="page" role="dialog" aria-modal="true" :aria-label="s.reader.title">
          <header>
            <div class="meta">
              {{ s.reader.subtitle }}
              <UiBadge v-if="s.reader.file" tone="accent">{{ s.reader.file }}</UiBadge>
            </div>
            <h1>{{ s.reader.title }}</h1>
            <div class="bar">
              <div class="tools">
                <button class="tool" aria-label="缩小字号" @click="size = Math.max(14, size - 1)">A−</button>
                <span class="size">{{ size }}</span>
                <button class="tool" aria-label="放大字号" @click="size = Math.min(24, size + 1)">A+</button>
              </div>
              <div class="links">
                <a v-if="s.reader.url" :href="s.reader.url" target="_blank" rel="noopener"
                   class="src" @click.stop>查看原文 ↗</a>
                <UiBtn size="sm" @click="closeReader()">关闭 (Esc)</UiBtn>
              </div>
            </div>
          </header>

          <nav v-if="toc.length" class="toc">
            <span class="toc-lb">目录</span>
            <a v-for="t in toc" :key="t.id" :href="'#' + t.id"
               :class="{ l3: t.level === 3 }">{{ t.text }}</a>
          </nav>

          <div class="body reading" :style="{ fontSize: size + 'px' }" v-html="body"></div>
        </article>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.overlay{position:fixed;inset:0;background:rgba(12,15,20,.46);backdrop-filter:blur(2px);
  z-index:var(--z-overlay);overflow-y:auto;padding:36px 16px 60px}
.page{max-width:780px;margin:0 auto;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r-lg);
  box-shadow:var(--shadow-lg);padding:36px 48px 56px}
header{border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:22px}
.meta{display:flex;align-items:center;gap:var(--sp-2);flex-wrap:wrap;
  font-size:var(--fs-sm);color:var(--ink3);margin-bottom:6px;word-break:break-all}
h1{margin:0 0 10px;font:600 var(--fs-xl)/1.4 var(--serif)}
.bar{display:flex;justify-content:space-between;align-items:center;gap:var(--sp-3);flex-wrap:wrap}
.tools{display:flex;align-items:center;gap:6px}
.tool{width:28px;height:24px;border:1px solid var(--line2);border-radius:var(--r-sm);
  font-size:var(--fs-xs);color:var(--ink2);background:var(--surface)}
.tool:hover{border-color:var(--accent);color:var(--accent-deep)}
.size{font:var(--fs-xs) var(--mono);color:var(--ink3);min-width:18px;text-align:center}
.links{display:flex;align-items:center;gap:var(--sp-3)}
.src{font-size:var(--fs-sm);color:var(--accent-deep)}

.toc{display:flex;flex-wrap:wrap;gap:var(--sp-2) var(--sp-3);align-items:baseline;
  padding:var(--sp-3);margin-bottom:var(--sp-4);border-radius:var(--r-md);
  background:var(--sunken);font-size:var(--fs-sm)}
.toc-lb{color:var(--ink3);font-size:var(--fs-xs)}
.toc a{color:var(--ink2)}
.toc a:hover{color:var(--accent-deep)}
.toc a.l3{padding-left:var(--sp-3);color:var(--ink3)}

.body{font-family:var(--serif);line-height:2.05;color:var(--ink)}
.body :deep(h1),.body :deep(h2),.body :deep(h3){font-family:var(--serif);
  margin:1.4em 0 .5em;line-height:1.4;scroll-margin-top:20px}
.body :deep(h2){font-size:1.25em}
.body :deep(h3){font-size:1.1em}
.body :deep(p){margin:.55em 0}
.body :deep(ul),.body :deep(ol){padding-left:1.6em;margin:.5em 0}
.body :deep(b){color:var(--accent-deep)}
.body :deep(pre){background:var(--sunken);padding:var(--sp-3);border-radius:var(--r-md);
  overflow-x:auto;font-size:.85em;line-height:1.7}
.body :deep(blockquote){border-left:3px solid var(--line2);margin:.6em 0;
  padding-left:var(--sp-3);color:var(--ink2)}

.reader-enter-active,.reader-leave-active{transition:opacity var(--dur-med)}
.reader-enter-from,.reader-leave-to{opacity:0}
@media(max-width:760px){.page{padding:24px 20px 40px}}
</style>

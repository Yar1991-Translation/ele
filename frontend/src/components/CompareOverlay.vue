<script setup>
/** 两篇对比：左右并排，各自滚动。ESC / 点遮罩关闭（与阅读器同一套手感）。 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useStore, closeCompare } from "../store.js";
import { mdToHtml } from "../md.js";
import { UiBtn } from "../ui";

const s = useStore();
const SIZE_KEY = "distiller-compare-size";
const size = ref(Number(localStorage.getItem(SIZE_KEY) || 15));
watch(size, v => localStorage.setItem(SIZE_KEY, String(v)));

const leftHtml = computed(() => s.compare ? mdToHtml(s.compare.left.content || "") : "");
const rightHtml = computed(() => s.compare ? mdToHtml(s.compare.right.content || "") : "");

function onKey(e){ if (e.key === "Escape") closeCompare(); }
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <transition name="cmp">
      <div v-if="s.compare" class="overlay" @click.self="closeCompare()">
        <div class="panes" role="dialog" aria-modal="true" aria-label="两篇对比">
          <header>
            <b>两篇对比</b>
            <div class="tools">
              <button class="tool" aria-label="缩小字号" @click="size = Math.max(12, size - 1)">A−</button>
              <span class="size">{{ size }}</span>
              <button class="tool" aria-label="放大字号" @click="size = Math.min(22, size + 1)">A+</button>
              <UiBtn size="sm" @click="closeCompare()">关闭 (Esc)</UiBtn>
            </div>
          </header>
          <div class="cols">
            <section class="col">
              <h3>{{ s.compare.left.name }}</h3>
              <div class="body reading" :style="{ fontSize: size + 'px' }"
                   v-html="leftHtml"></div>
            </section>
            <section class="col">
              <h3>{{ s.compare.right.name }}</h3>
              <div class="body reading" :style="{ fontSize: size + 'px' }"
                   v-html="rightHtml"></div>
            </section>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.overlay{position:fixed;inset:0;background:rgba(12,15,20,.46);backdrop-filter:blur(2px);
  z-index:var(--z-overlay);overflow-y:auto;padding:28px 16px 48px}
.panes{max-width:1280px;margin:0 auto;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r-lg);
  box-shadow:var(--shadow-lg);padding:var(--sp-4) var(--sp-5) var(--sp-5)}
header{display:flex;align-items:center;justify-content:space-between;
  gap:var(--sp-3);padding-bottom:var(--sp-3);border-bottom:1px solid var(--line)}
header b{font:600 var(--fs-md) var(--serif)}
.tools{display:flex;align-items:center;gap:6px}
.tool{width:28px;height:24px;border:1px solid var(--line2);border-radius:var(--r-sm);
  font-size:var(--fs-xs);color:var(--ink2);background:var(--surface)}
.tool:hover{border-color:var(--accent);color:var(--accent-deep)}
.size{font:var(--fs-xs) var(--mono);color:var(--ink3);min-width:18px;text-align:center}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-4);margin-top:var(--sp-3)}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.col{min-width:0;border:1px solid var(--line);border-radius:var(--r-md);overflow:hidden}
.col h3{margin:0;padding:var(--sp-2) var(--sp-3);background:var(--sunken);
  font:600 var(--fs-sm)/1.5 var(--ui);color:var(--ink2);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.body{padding:var(--sp-3) var(--sp-4);max-height:72vh;overflow-y:auto;
  font-family:var(--serif);line-height:2;color:var(--ink)}
.body :deep(h1),.body :deep(h2),.body :deep(h3){font-family:var(--serif);
  margin:1.2em 0 .5em;line-height:1.4}
.body :deep(h2){font-size:1.2em}
.body :deep(h3){font-size:1.05em}
.body :deep(p){margin:.55em 0}
.body :deep(pre){background:var(--sunken);padding:var(--sp-2);border-radius:var(--r-sm);
  overflow-x:auto;font-size:.85em}
.body :deep(blockquote){border-left:3px solid var(--line2);margin:.6em 0;
  padding-left:var(--sp-3);color:var(--ink2)}
.cmp-enter-active,.cmp-leave-active{transition:opacity var(--dur-med)}
.cmp-enter-from,.cmp-leave-to{opacity:0}
</style>

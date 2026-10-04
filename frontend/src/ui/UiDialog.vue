<script setup>
/** 模态框：role=dialog + aria-modal + 焦点陷阱 + ESC 关闭。
 *  焦点进来后 Tab 只在框内循环，关闭时把焦点还给打开它的元素。 */
import { ref, watch, nextTick, onBeforeUnmount } from "vue";

const props = defineProps({
  open: Boolean,
  title: { type: String, default: "" },
  desc: { type: String, default: "" },
  width: { type: String, default: "520px" },
  closable: { type: Boolean, default: true },
});
const emit = defineEmits(["close"]);

const box = ref(null);
let opener = null;

function focusables(){
  return [...(box.value?.querySelectorAll(
    'button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])') || [])]
    .filter(el => !el.disabled && el.offsetParent !== null);
}

function onKey(e){
  if (!props.open) return;
  if (e.key === "Escape" && props.closable){ e.preventDefault(); emit("close"); return; }
  if (e.key !== "Tab") return;
  const list = focusables();
  if (!list.length) return;
  const first = list[0], last = list[list.length - 1];
  if (e.shiftKey && document.activeElement === first){ e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last){ e.preventDefault(); first.focus(); }
}

watch(() => props.open, async (v) => {
  if (v){
    opener = document.activeElement;
    await nextTick();
    (focusables()[0] || box.value)?.focus();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
  } else {
    document.removeEventListener("keydown", onKey);
    document.body.style.overflow = "";
    opener?.focus?.();
    opener = null;
  }
});
onBeforeUnmount(() => {
  document.removeEventListener("keydown", onKey);
  document.body.style.overflow = "";
});
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="wrap" @mousedown.self="closable && emit('close')">
      <div ref="box" class="dlg" role="dialog" aria-modal="true"
           :aria-label="title || '对话框'" :style="{ width }" tabindex="-1">
        <header class="hd">
          <div>
            <h3>{{ title }}</h3>
            <p v-if="desc" class="desc">{{ desc }}</p>
          </div>
          <button v-if="closable" class="x" aria-label="关闭" @click="emit('close')">×</button>
        </header>
        <div class="bd"><slot /></div>
        <footer v-if="$slots.footer" class="ft"><slot name="footer" /></footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.wrap{position:fixed;inset:0;z-index:var(--z-dialog);
  background:rgba(12,15,20,.42);backdrop-filter:blur(2px);
  display:flex;align-items:center;justify-content:center;padding:var(--sp-5)}
.dlg{background:var(--raised);border:1px solid var(--line);border-radius:var(--r-lg);
  box-shadow:var(--shadow-lg);max-width:100%;max-height:88vh;display:flex;
  flex-direction:column;outline:none}
.hd{display:flex;align-items:flex-start;justify-content:space-between;
  gap:var(--sp-4);padding:var(--sp-5) var(--sp-5) var(--sp-3)}
.hd h3{font:600 var(--fs-md)/1.4 var(--serif)}
.desc{margin:4px 0 0;font-size:var(--fs-sm);color:var(--ink3);line-height:1.6}
.x{flex:none;width:28px;height:28px;border-radius:var(--r-sm);color:var(--ink3);
  font-size:20px;line-height:1}
.x:hover{background:var(--hover);color:var(--ink)}
.bd{padding:0 var(--sp-5) var(--sp-5);overflow-y:auto}
.ft{display:flex;justify-content:flex-end;gap:var(--sp-2);
  padding:var(--sp-3) var(--sp-5);border-top:1px solid var(--line);background:var(--bg)}
</style>

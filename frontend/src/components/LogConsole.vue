<script setup>
import { watch, ref } from "vue";
import { useStore } from "../store.js";
const s = useStore();

// 日志着色：阶段标记琥珀、异常红
const kind = (text) => /^——/.test(text) ? "mark"
  : /(失败|限流|错误|Traceback|Error)/.test(text) ? "warn" : "";

// 距底 60px 内才粘底滚动。
// 必须是 ref()：普通变量作模板 ref 在生产构建会被编译器丢弃，导致永远不粘底。
const el = ref(null);
watch(() => s.logs.length, () => {
  const node = el.value;
  if (!node) return;
  const stick = node.scrollHeight - node.scrollTop - node.clientHeight < 60;
  if (stick) node.scrollTop = node.scrollHeight;
});
</script>

<template>
  <div ref="el" class="console">
    <div v-if="!s.logs.length" class="empty">
      运行记录会显示在这里。第一次使用：先到「配置」填 tag 和密钥，再回来开始爬取。
    </div>
    <div v-for="e in s.logs" :key="e.i" class="line" :class="kind(e.text)">
      <span class="t">{{ e.t }}</span>{{ e.text }}
    </div>
  </div>
</template>

<style scoped>
.console{background:#2b2823;border:1px solid var(--line);border-radius:var(--r-lg);
  height:380px;overflow-y:auto;padding:12px 14px;
  font:12.5px/1.75 var(--mono);white-space:pre-wrap;word-break:break-all;
  color:#d8d0c2}
.line{animation:fadein .25s}
.line .t{color:#8b8272;margin-right:8px}
.line.mark{color:#dcae6e}
.line.warn{color:#e08a80}
@keyframes fadein{from{opacity:0}}
.empty{color:#8b8272;font:13px var(--ui)}
</style>

<script setup>
/** 卡片：标题 + 说明 + 内容，说明常驻显示（不藏在 hover 里）。 */
defineProps({
  title: { type: String, default: "" },
  desc: { type: String, default: "" },
  flush: Boolean,   // 内容区不加内边距（表格用）
});
</script>

<template>
  <section class="ucard">
    <header v-if="title || $slots.extra" class="hd">
      <div>
        <h3 v-if="title">{{ title }}</h3>
        <p v-if="desc" class="desc">{{ desc }}</p>
      </div>
      <div v-if="$slots.extra" class="extra"><slot name="extra" /></div>
    </header>
    <div class="bd" :class="{ flush }"><slot /></div>
    <footer v-if="$slots.footer" class="ft"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.ucard{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-lg);box-shadow:var(--shadow-sm);overflow:hidden}
.hd{display:flex;align-items:flex-start;justify-content:space-between;
  gap:var(--sp-4);padding:var(--sp-4) var(--sp-5) 0}
.hd h3{font:600 var(--fs-md)/1.4 var(--serif)}
.desc{margin:4px 0 0;font-size:var(--fs-sm);color:var(--ink3);line-height:1.65}
.extra{flex:none;display:flex;gap:var(--sp-2);align-items:center}
.bd{padding:var(--sp-4) var(--sp-5) var(--sp-5)}
.bd.flush{padding:0}
.ft{padding:var(--sp-3) var(--sp-5);border-top:1px solid var(--line);background:var(--bg)}
</style>

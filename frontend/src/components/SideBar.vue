<script setup>
/** 侧栏：按用户任务组织导航（不是按技术阶段）。 */
import { computed } from "vue";
import { useStore, switchView } from "../store.js";

const s = useStore();

const NAV = [
  { key: "home", label: "总览", icon: "◎", desc: "还差什么、有什么" },
  { key: "materials", label: "素材", icon: "▤", desc: "爬取 · 过滤 · 蒸馏" },
  { key: "write", label: "写作", icon: "✎", desc: "写下想法生成文章" },
  { key: "library", label: "成果", icon: "❑", desc: "读、导出、管理" },
  { key: "settings", label: "设置", icon: "⚙", desc: "登录 · 模型 · 参数" },
];

const MODE_NAME = { auto: "自动生成", quick: "关键词速写", self: "我自己写",
                    polish: "润色原稿", expand: "扩充原稿", team: "团队润色" };

const brief = computed(() => [
  ["标签", s.config?.crawl?.tag || "未填"],
  ["方式", MODE_NAME[s.config?.write?.mode] || "自动生成"],
  ["知识库", (s.stats?.knowledge || []).length + " 份"],
]);
</script>

<template>
  <aside class="side">
    <div class="brand">
      <span class="mark" aria-hidden="true">⚗</span>
      <span class="name">蒸馏工坊</span>
    </div>

    <nav class="nav" aria-label="主导航">
      <button v-for="n in NAV" :key="n.key" class="item"
              :class="{ on: s.view === n.key }"
              :aria-current="s.view === n.key ? 'page' : undefined"
              @click="switchView(n.key)">
        <span class="ico" aria-hidden="true">{{ n.icon }}</span>
        <span class="tx">
          <b>{{ n.label }}</b>
          <em>{{ n.desc }}</em>
        </span>
      </button>
    </nav>

    <div class="brief">
      <div class="hd">当前设置</div>
      <div v-for="[k, v] in brief" :key="k" class="row">
        <span>{{ k }}</span><b>{{ v }}</b>
      </div>
    </div>

    <div class="foot">v{{ s.server_version || "—" }}</div>
  </aside>
</template>

<style scoped>
.side{position:sticky;top:0;height:100vh;display:flex;flex-direction:column;
  gap:var(--sp-5);padding:var(--sp-5) var(--sp-3);
  border-right:1px solid var(--line);background:var(--surface)}
.brand{display:flex;align-items:center;gap:var(--sp-2);padding:0 var(--sp-2)}
.mark{font-size:20px;color:var(--accent)}
.name{font:600 var(--fs-md) var(--serif);letter-spacing:2px}

.nav{display:flex;flex-direction:column;gap:2px}
.item{display:flex;align-items:flex-start;gap:var(--sp-2);
  padding:var(--sp-2) var(--sp-3);border-radius:var(--r-md);text-align:left;
  transition:background var(--dur-fast),color var(--dur-fast)}
.item:hover{background:var(--hover)}
.item.on{background:var(--accent-soft);color:var(--accent-deep)}
.ico{flex:none;font-size:15px;line-height:1.5;opacity:.75}
.tx{display:flex;flex-direction:column;gap:1px;min-width:0}
.tx b{font-size:var(--fs-base);line-height:1.5}
.tx em{font-style:normal;font-size:var(--fs-xs);color:var(--ink3);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item.on .tx em{color:var(--accent-deep);opacity:.8}

.brief{margin-top:auto;padding:var(--sp-3);border-radius:var(--r-md);background:var(--sunken)}
.brief .hd{font-size:var(--fs-xs);color:var(--ink3);margin-bottom:6px}
.brief .row{display:flex;justify-content:space-between;gap:var(--sp-2);
  font-size:var(--fs-xs);padding:2px 0}
.brief .row span{color:var(--ink3)}
.brief .row b{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

.foot{text-align:center;font:var(--fs-xs) var(--mono);color:var(--ink3)}

@media(max-width:900px){
  .side{padding:var(--sp-3) var(--sp-1);gap:var(--sp-3)}
  .name,.tx em,.brief,.foot{display:none}
  .brand{justify-content:center}
  .item{justify-content:center;padding:var(--sp-2)}
  .tx b{font-size:var(--fs-xs)}
}
</style>

<script setup>
import { computed } from "vue";
import { useStore, init, switchView, toast } from "./store.js";
import { useTheme } from "./ui";
import SideBar from "./components/SideBar.vue";
import ToastHost from "./components/ToastHost.vue";
import ReaderOverlay from "./components/ReaderOverlay.vue";
import CompareOverlay from "./components/CompareOverlay.vue";
import TaskBar from "./components/TaskBar.vue";
import FirstRunWizard from "./components/FirstRunWizard.vue";
import HomeView from "./views/HomeView.vue";
import MaterialsView from "./views/MaterialsView.vue";
import WriteView from "./views/WriteView.vue";
import LibraryView from "./views/LibraryView.vue";
import SettingsView from "./views/SettingsView.vue";

const s = useStore();
const { theme, setTheme } = useTheme();
init();

const TITLES = {
  home: "总览", materials: "素材", write: "写作",
  library: "成果", settings: "设置",
};
const stageName = computed(() =>
  ({ crawl: "爬取", filter: "过滤", distill: "蒸馏", write: "写作",
     runall: "一键跑素材", selftest: "自测", chars: "角色卡" }[s.running] || s.running));

const THEME_CYCLE = { auto: "light", light: "dark", dark: "auto" };
</script>

<template>
  <div class="shell">
    <SideBar />

    <main class="main">
      <header class="topbar">
        <h2>{{ TITLES[s.view] }}</h2>
        <div class="right">
          <button class="theme" :title="'主题：' + ({ auto: '跟随系统', light: '浅色', dark: '深色' }[theme.mode])"
                  @click="setTheme(THEME_CYCLE[theme.mode])">
            {{ { auto: "◐", light: "☀", dark: "☾" }[theme.mode] || "◐" }}
            {{ { auto: "跟随系统", light: "浅色", dark: "深色" }[theme.mode] }}
          </button>
          <div class="status" :class="{ on: s.running }">
            <span class="dot"></span>
            {{ s.running ? "运行中 · " + stageName : "空闲" }}
          </div>
        </div>
      </header>

      <!-- 单根 + v-show：多根组件的 v-show 会失效（踩过坑） -->
      <HomeView v-show="s.view === 'home'" />
      <MaterialsView v-show="s.view === 'materials'" />
      <WriteView v-show="s.view === 'write'" />
      <LibraryView v-show="s.view === 'library'" />
      <SettingsView v-show="s.view === 'settings'" />

      <TaskBar />
    </main>

    <ToastHost />
    <ReaderOverlay />
    <CompareOverlay />
    <FirstRunWizard />
  </div>
</template>

<style scoped>
.shell{display:grid;grid-template-columns:212px 1fr;min-height:100vh}
.main{padding:24px 32px 32px;width:100%;max-width:1360px;margin:0 auto;
  display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;justify-content:space-between;
  gap:var(--sp-4);margin-bottom:var(--sp-4)}
.topbar h2{margin:0;font:600 var(--fs-xl)/1.2 var(--serif);letter-spacing:1.5px}
.right{display:flex;align-items:center;gap:var(--sp-3)}
.theme{display:flex;align-items:center;gap:6px;padding:5px 12px;
  border:1px solid var(--line2);border-radius:var(--r-full);
  font-size:var(--fs-xs);color:var(--ink2);background:var(--surface)}
.theme:hover{border-color:var(--accent);color:var(--accent-deep)}
.status{display:flex;align-items:center;gap:7px;color:var(--ink2);
  font-size:var(--fs-sm);white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:var(--line2)}
.status.on{color:var(--ink)}
.status.on .dot{background:var(--accent);animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}

@media(max-width:900px){
  .shell{grid-template-columns:60px 1fr}
  .main{padding:var(--sp-4)}
}
</style>

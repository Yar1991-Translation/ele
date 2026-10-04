/** 主题：light / dark / auto（跟随系统）。选择存在 localStorage。 */
import { reactive, watchEffect } from "vue";

const KEY = "distiller-theme";
const state = reactive({ mode: localStorage.getItem(KEY) || "auto" });

function resolve(){
  if (state.mode === "dark") return "dark";
  if (state.mode === "light") return "light";
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function apply(){
  document.documentElement.setAttribute("data-theme", resolve());
}

watchEffect(() => { state.mode; apply(); });

if (window.matchMedia){
  window.matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => state.mode === "auto" && apply());
}

export function useTheme(){
  return {
    theme: state,
    setTheme(mode){
      state.mode = mode;
      localStorage.setItem(KEY, mode);
      apply();
    },
    resolved: resolve,
  };
}

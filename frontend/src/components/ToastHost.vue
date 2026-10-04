<script setup>
/** 轻提示：aria-live 让读屏软件也能听到（M2 无障碍补全）。 */
import { useStore } from "../store.js";
const s = useStore();
</script>

<template>
  <transition name="toast">
    <div v-if="s.toast" id="toast" role="status" aria-live="polite"
         :class="{ err: s.toast.err }">{{ s.toast.msg }}</div>
  </transition>
</template>

<style scoped>
#toast{position:fixed;right:20px;bottom:20px;max-width:440px;background:var(--raised);
  border:1px solid var(--accent);border-radius:var(--r-md);padding:11px 16px;font-size:13.5px;
  box-shadow:var(--shadow-lg);z-index:var(--z-toast)}
#toast.err{border-color:var(--red);color:var(--red)}
.toast-enter-active,.toast-leave-active{transition:opacity var(--dur-med), transform var(--dur-med)}
.toast-enter-from,.toast-leave-to{opacity:0;transform:translateY(6px)}
</style>

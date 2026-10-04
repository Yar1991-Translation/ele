/** 实锤 bug 的回归断言（与后端 tests/test_gui_api.py 双保险，防回退）。 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mount } from "@vue/test-utils";
import UiSelect from "../src/ui/UiSelect.vue";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const read = (p) => readFileSync(join(ROOT, p), "utf-8");

describe("6 个实锤 bug 的修复断言", () => {
  it("bug1：人设导入按钮用 ref 句柄，不再 $refs.personaFile", () => {
    const s = read("views/MaterialsView.vue");
    expect(s).toContain("personaInput.click()");
    expect(s).not.toContain("$refs.personaFile");
  });

  it("bug2：日志粘底的模板 ref 是 ref()（生产构建才会生效）", () => {
    const s = read("components/LogConsole.vue");
    expect(s).toContain("const el = ref(null)");
    expect(s).not.toContain("let el = null");
    expect(s).toContain("el.value");
  });

  it("bug5：侧栏写作方式映射含 team（团队润色不再显示成自动生成）", () => {
    const s = read("components/SideBar.vue");
    expect(s).toMatch(/team:\s*"团队润色"/);
  });

  it("bug6：阶段名映射认得 chars（角色卡阶段不再像卡死）", () => {
    const materials = read("views/MaterialsView.vue");
    for (const k of ['key: "chars"', 'key: "crawl"', 'key: "filter"', 'key: "distill"']) {
      expect(materials).toContain(k);
    }
    const taskbar = read("components/TaskBar.vue");
    expect(taskbar).toContain('chars: "角色卡"');
  });
});

describe("连带修复：UiSelect 认 [值,标签] 对", () => {
  it("config_schema 的 choices 形状能正确渲染", () => {
    const w = mount(UiSelect, {
      props: { modelValue: "new", options: [["new", "最新优先"], ["date", "按天回溯"]] },
    });
    const opts = w.findAll("option");
    expect(opts[0].attributes("value")).toBe("new");
    expect(opts[0].text()).toBe("最新优先");
  });
});

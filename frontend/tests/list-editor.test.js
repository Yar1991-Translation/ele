/** 行式编辑器：提供商（providerlist）与团队成员（agentlist）的渲染、增删行、字段编辑。 */
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import UiListEditor from "../src/ui/UiListEditor.vue";

const PROVIDER_COLS = [
  { key: "name", label: "名称", width: "0.8" },
  { key: "base_url", label: "接口地址", width: "2" },
  { key: "api_key", label: "密钥", type: "password", width: "1.2" },
];
const AGENT_COLS = [
  { key: "name", label: "成员名", width: "0.8" },
  { key: "model", label: "模型", width: "1.4" },
  { key: "thinking", label: "思考强度", type: "select", width: "0.6",
    options: [["", "关"], ["低", "低"], ["中", "中"], ["高", "高"]] },
  { key: "perspective", label: "职责视角", width: "2" },
];

describe("UiListEditor", () => {
  it("空数组显示空提示与添加按钮", () => {
    const w = mount(UiListEditor, { props: { modelValue: [], columns: PROVIDER_COLS,
                                             addLabel: "添加提供商", emptyHint: "还没有提供商" } });
    expect(w.text()).toContain("还没有提供商");
    expect(w.text()).toContain("添加提供商");
  });

  it("渲染已有行，密码列渲染为 password 输入框", () => {
    const w = mount(UiListEditor, { props: { modelValue: [
      { name: "ds", base_url: "https://x", api_key: "sk-a****" }] , columns: PROVIDER_COLS } });
    expect(w.find("input[type=password]").exists()).toBe(true);
    const values = w.findAll("input").map(i => i.element.value);
    expect(values).toContain("ds");
    expect(values).toContain("https://x");
  });

  it("select 列渲染思考强度档位", () => {
    const w = mount(UiListEditor, { props: { modelValue: [
      { name: "文风编辑", model: "", thinking: "高", perspective: "看文风" }], columns: AGENT_COLS } });
    const sel = w.find("select");
    expect(sel.exists()).toBe(true);
    expect(sel.findAll("option").map(o => o.text())).toEqual(["关", "低", "中", "高"]);
    expect(sel.element.value).toBe("高");
  });

  it("添加行：发带新行对象的 update:modelValue", async () => {
    const w = mount(UiListEditor, { props: { modelValue: [], columns: AGENT_COLS,
                                             newRow: { name: "", model: "", thinking: "", perspective: "" } } });
    await w.find("button.add").trigger("click");
    expect(w.emitted("update:modelValue")[0][0]).toEqual([
      { name: "", model: "", thinking: "", perspective: "" }]);
  });

  it("编辑字段：发整行更新后的新数组", async () => {
    const w = mount(UiListEditor, { props: { modelValue: [
      { name: "ds", base_url: "", api_key: "" }], columns: PROVIDER_COLS } });
    await w.findAll("input")[0].setValue("deepseek");
    const evt = w.emitted("update:modelValue");
    expect(evt.length).toBeGreaterThan(0);
    expect(evt[evt.length - 1][0][0]).toEqual({ name: "deepseek", base_url: "", api_key: "" });
  });

  it("删除行：发去掉该行后的新数组", async () => {
    const w = mount(UiListEditor, { props: { modelValue: [
      { name: "a", base_url: "", api_key: "" },
      { name: "b", base_url: "", api_key: "" }], columns: PROVIDER_COLS } });
    await w.findAll("button.del")[1].trigger("click");
    expect(w.emitted("update:modelValue")[0][0].map(r => r.name)).toEqual(["a"]);
  });
});

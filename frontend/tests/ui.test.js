/** UI 组件集渲染测试：走令牌的小白友好控件，形态别悄悄变。 */
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import UiBtn from "../src/ui/UiBtn.vue";
import UiSelect from "../src/ui/UiSelect.vue";
import UiSwitch from "../src/ui/UiSwitch.vue";
import UiTabs from "../src/ui/UiTabs.vue";
import UiField from "../src/ui/UiField.vue";
import UiProgress from "../src/ui/UiProgress.vue";

describe("UiBtn", () => {
  it("渲染文案并转发点击", async () => {
    const w = mount(UiBtn, { slots: { default: "开始写作" } });
    expect(w.text()).toContain("开始写作");
    await w.find("button").trigger("click");
    expect(w.emitted("click")).toBeTruthy();
  });

  it("disabled / loading 都不可点，loading 有 aria-busy", () => {
    const d = mount(UiBtn, { props: { disabled: true } });
    expect(d.find("button").attributes("disabled")).toBeDefined();
    const l = mount(UiBtn, { props: { loading: true } });
    expect(l.find("button").attributes("disabled")).toBeDefined();
    expect(l.find("button").attributes("aria-busy")).toBe("true");
    expect(l.find(".spin").exists()).toBe(true);
  });
});

describe("UiSelect", () => {
  it("接受 {value,label} 对象", () => {
    const w = mount(UiSelect, {
      props: { modelValue: "a", options: [{ value: "a", label: "甲" }, { value: "b", label: "乙" }] },
    });
    const opts = w.findAll("option");
    expect(opts.length).toBe(2);
    expect(opts[1].text()).toBe("乙");
  });

  it("接受 [值,标签] 数组对（config_schema choices 就是这个形状）", () => {
    const w = mount(UiSelect, {
      props: { modelValue: "new", options: [["new", "最新优先"], ["date", "按天回溯"]] },
    });
    const opts = w.findAll("option");
    expect(opts.length).toBe(2);
    expect(opts[0].attributes("value")).toBe("new");
    expect(opts[0].text()).toBe("最新优先");
  });

  it("接受纯字符串数组", () => {
    const w = mount(UiSelect, { props: { modelValue: "男男", options: ["微量", "男男"] } });
    expect(w.findAll("option")[1].text()).toBe("男男");
  });

  it("选择后 emit update:modelValue", async () => {
    const w = mount(UiSelect, {
      props: { modelValue: "a", options: [["a", "甲"], ["b", "乙"]] },
    });
    await w.find("select").setValue("b");
    expect(w.emitted("update:modelValue")[0]).toEqual(["b"]);
  });
});

describe("UiSwitch", () => {
  it("切换 emit 布尔值", async () => {
    const w = mount(UiSwitch, { props: { modelValue: false, label: "用 AI 逐篇判定" } });
    expect(w.find("input").element.checked).toBe(false);
    await w.find("input").setValue(true);
    expect(w.emitted("update:modelValue")[0]).toEqual([true]);
    expect(w.text()).toContain("用 AI 逐篇判定");
  });
});

describe("UiTabs", () => {
  it("点标签切换并带 aria-selected", async () => {
    const w = mount(UiTabs, {
      props: { modelValue: "a", items: [{ key: "a", label: "文章" }, { key: "b", label: "知识库" }] },
    });
    expect(w.findAll('[role="tab"]')[0].attributes("aria-selected")).toBe("true");
    await w.findAll('[role="tab"]')[1].trigger("click");
    expect(w.emitted("update:modelValue")[0]).toEqual(["b"]);
  });
});

describe("UiField", () => {
  it("标签 / 说明 / 单位 / 必填 都渲染", () => {
    const w = mount(UiField, {
      props: { label: "目标篇幅", help: "生成文章大概多少字", unit: "字", required: true },
      slots: { default: "<input>" },
    });
    expect(w.text()).toContain("目标篇幅");
    expect(w.text()).toContain("生成文章大概多少字");
    expect(w.text()).toContain("字");
    expect(w.text()).toContain("必填");
  });
});

describe("UiProgress", () => {
  it("进度条带 role=progressbar 与 aria 值", () => {
    const w = mount(UiProgress, { props: { percent: 42, label: "章节 2/5" } });
    const bar = w.find('[role="progressbar"]');
    expect(bar.exists()).toBe(true);
    expect(bar.attributes("aria-valuenow")).toBe("42");
    expect(bar.attributes("aria-valuemin")).toBe("0");
    expect(bar.attributes("aria-valuemax")).toBe("100");
  });
});

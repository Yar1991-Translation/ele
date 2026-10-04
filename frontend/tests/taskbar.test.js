/** 任务条提问面板：LLM 提问 -> 用户点选项/输入 -> 提交 /api/answer。 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import TaskBar from "../src/components/TaskBar.vue";
import { useStore } from "../src/store.js";

const QUESTION = {
  id: "q1",
  title: "动笔前确认",
  items: [
    { q: "重逢放在雨夜还是雪夜？", options: ["雨夜", "雪夜"], suggest: "雨夜" },
    { q: "结尾要留希望吗？", options: ["留一线希望", "彻底断绝"], suggest: "留一线希望" },
  ],
  expires_at: null,
};

describe("TaskBar 提问面板", () => {
  let s;

  beforeEach(() => {
    s = useStore();
    s.question = JSON.parse(JSON.stringify(QUESTION));
    s.running = null;
    s.stageResult = null;
    s.progress = null;
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ ok: true }) })));
  });

  afterEach(() => {
    s.question = null;
    vi.unstubAllGlobals();
  });

  it("有问题时展示问题、选项 chips 与建议占位", () => {
    const w = mount(TaskBar);
    expect(w.text()).toContain("动笔前确认");
    expect(w.text()).toContain("重逢放在雨夜还是雪夜？");
    expect(w.text()).toContain("结尾要留希望吗？");
    expect(w.findAll("button.achip").length).toBe(4);
    expect(w.find("input.ain").attributes("placeholder")).toContain("默认：雨夜");
  });

  it("点选项后提交，答案发到 /api/answer", async () => {
    const w = mount(TaskBar);
    await w.findAll("button.achip")[1].trigger("click");       // 雪夜
    const submit = w.findAll("button").find(b => b.text().includes("回答并继续"));
    await submit.trigger("click");
    await flushPromises();

    const call = fetch.mock.calls.find(c => String(c[0]).includes("/api/answer"));
    expect(call).toBeTruthy();
    const body = JSON.parse(call[1].body);
    expect(body.id).toBe("q1");
    expect(body.answers["0"]).toBe("雪夜");
    expect(body.answers["1"]).toBe("留一线希望");   // 没选的用建议
    expect(body.skip).toBe(false);
    expect(s.question).toBe(null);                  // 提交后面板立刻收起
  });

  it("自由输入优先于选项；跳过带 skip 标记", async () => {
    const w = mount(TaskBar);
    await w.findAll("input.ain")[0].setValue("黄昏也可以");
    await w.findAll("button").find(b => b.text().includes("回答并继续")).trigger("click");
    await flushPromises();
    let body = JSON.parse(fetch.mock.calls.find(c => String(c[0]).includes("/api/answer"))[1].body);
    expect(body.answers["0"]).toBe("黄昏也可以");

    s.question = JSON.parse(JSON.stringify(QUESTION));
    await flushPromises();
    await w.findAll("button").find(b => b.text().includes("跳过")).trigger("click");
    await flushPromises();
    body = JSON.parse(fetch.mock.calls.filter(c => String(c[0]).includes("/api/answer")).pop()[1].body);
    expect(body.skip).toBe(true);
  });

  it("没有问题时不渲染提问面板", () => {
    s.question = null;
    const w = mount(TaskBar);
    expect(w.text()).not.toContain("动笔前确认");
    expect(w.find(".ask").exists()).toBe(false);
  });
});

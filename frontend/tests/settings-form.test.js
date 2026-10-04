/** 设置页表单生成：后端 schema 长什么样，界面就该长出什么控件。 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import SettingsView from "../src/views/SettingsView.vue";
import { useStore } from "../src/store.js";

const SCHEMA = {
  fields: [
    { path: "crawl.tag", type: "str", default: "", label: "标签名",
      help: "话题标签", group: "basic", advanced: false, required: true },
    { path: "crawl.sort", type: "str", default: "new", label: "翻页方式",
      help: "怎么翻页", group: "basic", advanced: false,
      choices: [["new", "最新优先"], ["date", "按天回溯"]] },
    { path: "crawl.max_count", type: "int", default: 0, label: "爬取篇数上限",
      help: "0=不限", group: "basic", advanced: false, unit: "篇", min: 0 },
    { path: "filter.llm_judge", type: "bool", default: true, label: "用 AI 逐篇判定",
      help: "关掉就全保留", group: "filter", advanced: false },
    { path: "filter.keywords", type: "list", default: [], label: "关键词黑名单",
      help: "一行一个", group: "filter", advanced: false },
    { path: "distill.focus", type: "list", default: ["style"], label: "生成哪些知识库",
      help: "多选", group: "distill", advanced: false,
      choices: [["style", "文风"], ["warnings", "雷点"]] },
    { path: "write.length", type: "int", default: 8000, label: "目标篇幅",
      help: "字数", group: "write", advanced: true, unit: "字", min: 500 },
    { path: "providers", type: "providerlist", default: [], label: "更多提供商",
      help: "其他 OpenAI 兼容提供商", group: "providers", advanced: false },
    { path: "team.agents", type: "agentlist", default: [], label: "团队成员",
      help: "评审成员", group: "team", advanced: false },
  ],
  groups: [
    { key: "basic", label: "基础", help: "最少要配的" },
    { key: "filter", label: "过滤", help: "排除什么" },
    { key: "distill", label: "蒸馏", help: "提炼什么" },
    { key: "write", label: "写作", help: "生成默认值" },
    { key: "providers", label: "模型提供商", help: "更多提供商" },
    { key: "team", label: "团队润色", help: "评审成员" },
  ],
  env: [
    { path: "LOFTER_COOKIE", label: "Lofter Cookie", secret: true, help: "登录用" },
    { path: "LLM_MODEL", label: "主模型", secret: false, help: "模型名" },
  ],
  presets: [
    { key: "trial", label: "试跑 20 篇（省钱）", desc: "小规模", values: { "crawl.max_count": 20 } },
    { key: "standard", label: "标准", desc: "日常", values: { "crawl.max_count": 0 } },
    { key: "fine", label: "精细（更慢更贵）", desc: "质量优先", values: { "crawl.max_count": 0 } },
  ],
};

function mockFetch(){
  return vi.fn(async (url) => {
    const u = String(url);
    if (u.includes("/api/config-schema")) return { ok: true, json: async () => SCHEMA };
    if (u.includes("/api/prompts")) return { ok: true, json: async () => ({ items: [] }) };
    return { ok: true, json: async () => ({}) };
  });
}

describe("SettingsView 表单生成", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
    const s = useStore();
    s.config = { crawl: { tag: "洲回响", sort: "new", max_count: 0 },
                 filter: { llm_judge: true, keywords: ["乙女向"] } };
    s.env = { LLM_MODEL: { set: true, hint: "", value: "mimo-test" } };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("按 schema 渲染控件：文本/下拉/数字/开关/多选/列表", async () => {
    const w = mount(SettingsView);
    await flushPromises();

    // 基础组默认可见的字段
    expect(w.text()).toContain("标签名");
    expect(w.text()).toContain("翻页方式");
    expect(w.text()).toContain("爬取篇数上限");
    // 下拉是选择框而不是空的
    const selects = w.findAll("select");
    expect(selects.length).toBeGreaterThan(0);
    const optTexts = selects.map(sel => sel.findAll("option").map(o => o.text()).join("|"));
    expect(optTexts.some(t => t.includes("最新优先") && t.includes("按天回溯"))).toBe(true);

    // 切到「过滤」组看开关与列表
    const tabs = w.findAll('[role="tab"]');
    const filterTab = tabs.find(t => t.text().includes("过滤"));
    await filterTab.trigger("click");
    expect(w.find("input[type=checkbox].sr, label.sw input[type=checkbox]").exists()).toBe(true);
    expect(w.find("textarea").exists()).toBe(true);

    // 高级字段默认收起，展开后出现
    expect(w.text()).not.toContain("目标篇幅");
    const advBtn = w.findAll("button").find(b => b.text().includes("显示高级"));
    await advBtn.trigger("click");
    const writeTab = w.findAll('[role="tab"]').find(t => t.text().includes("写作"));
    await writeTab.trigger("click");
    expect(w.text()).toContain("目标篇幅");
  });

  it("预设档位一键套用打脏标记", async () => {
    const w = mount(SettingsView);
    await flushPromises();
    const trial = w.findAll("button.preset").find(b => b.text().includes("试跑"));
    await trial.trigger("click");
    expect(w.text()).toContain("有未保存的修改");
  });

  it("env 表单渲染：密文有掩码占位，非密文回显现值", async () => {
    const w = mount(SettingsView);
    await flushPromises();
    expect(w.text()).toContain("Lofter Cookie");
    expect(w.text()).toContain("主模型");
    const pwd = w.find('input[type="password"]');
    expect(pwd.exists()).toBe(true);
    expect(pwd.attributes("placeholder")).toContain("粘贴到这里");
  });

  it("providerlist 用行式编辑器渲染，密钥是密码框", async () => {
    useStore().config = { providers: [{ name: "ds", base_url: "https://x", api_key: "sk-a****" }] };
    const w = mount(SettingsView);
    await flushPromises();
    const tab = w.findAll('[role="tab"]').find(t => t.text().includes("模型提供商"));
    await tab.trigger("click");
    expect(w.text()).toContain("更多提供商");
    const rows = w.findAll(".lre .row");
    expect(rows.length).toBe(1);
    expect(rows[0].find("input[type=password]").exists()).toBe(true);
    expect(rows[0].findAll("input").map(i => i.element.value)).toContain("ds");
  });

  it("agentlist 用行式编辑器渲染（含思考强度下拉）", async () => {
    useStore().config = { team: { agents: [
      { name: "文风编辑", model: "", thinking: "高", perspective: "看文风" }] } };
    const w = mount(SettingsView);
    await flushPromises();
    const tab = w.findAll('[role="tab"]').find(t => t.text().includes("团队润色"));
    await tab.trigger("click");
    const rows = w.findAll(".lre .row");
    expect(rows.length).toBe(1);
    expect(rows[0].find("select").exists()).toBe(true);
  });

  it("提示词 tab 挂出独立编辑面板", async () => {
    const w = mount(SettingsView);
    await flushPromises();
    const pTab = w.findAll('[role="tab"]').find(t => t.text().includes("提示词"));
    await pTab.trigger("click");
    await flushPromises();
    expect(w.text()).toContain("模板");
    // 提示词 tab 不再显示「保存全部设置」
    const saveAll = w.findAll("button").find(b => b.text().includes("保存全部设置"));
    expect(saveAll).toBeFalsy();
  });
});

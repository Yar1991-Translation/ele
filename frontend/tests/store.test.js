/** store 纯逻辑测试：进度行解析、toast、主题。 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { isProgressLine, useStore, toast } from "../src/store.js";
import { useTheme } from "../src/ui/theme.js";

describe("进度行解析", () => {
  it("识别自定义进度标记", () => {
    expect(isProgressLine("# 进度：章节 2/5")).toBe(true);
    expect(isProgressLine("# 进度：角色 3/39")).toBe(true);
  });

  it("普通日志行不是进度行", () => {
    expect(isProgressLine("[12/39] 正在写第 12 章")).toBe(false);
    expect(isProgressLine("开始爬取")).toBe(false);
    expect(isProgressLine("")).toBe(false);
  });
});

describe("toast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("报错态和自动消失", () => {
    const s = useStore();
    toast("出事了", true);
    expect(s.toast).toEqual({ msg: "出事了", err: true });
    vi.advanceTimersByTime(4300);
    expect(s.toast).toBe(null);
  });
});

describe("主题", () => {
  const KEY = "distiller-theme";
  beforeEach(() => localStorage.removeItem(KEY));

  it("setTheme 写 data-theme 并持久化", () => {
    const { setTheme, theme } = useTheme();
    setTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(KEY)).toBe("dark");
    expect(theme.mode).toBe("dark");
    setTheme("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(localStorage.getItem(KEY)).toBe("light");
  });
});

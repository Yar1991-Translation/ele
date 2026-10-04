# -*- coding: utf-8 -*-
"""GUI 后端与前端契约回归测试（沙盒离线，不碰真实数据）。

覆盖：6 个实锤 bug 的修复、config_schema 完整性、新 API、配置注释保留、
@ 点名正则前后端一致性。

运行：python -m tests.test_gui_api
"""
import io
import os
import re
import shutil
import sys
import tempfile
import types

# Windows 控制台默认 GBK，打印 ✓ 会炸——统一按 UTF-8 出
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

SANDBOX = tempfile.mkdtemp(prefix="gui_api_")
os.environ["DISTILLER_DATA_DIR"] = SANDBOX        # 必须早于 storage 的 import

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CONFIG_PATH = os.path.join(ROOT, "config.yaml")

from gui import config_schema  # noqa: E402
from gui.server import app, ALLOWED_CONFIG  # noqa: E402
from spider import storage  # noqa: E402

storage.ensure_dirs()          # 沙盒目录建好，后续测试直接写文件
_ok = []


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError("{}：{}".format(name, detail))
    _ok.append(name)
    print("  ✓", name)


# ======================================================================
# bug 1/2/5/6：前端契约（JS 无法离线跑，用源码断言防止回退）
# ======================================================================
def test_frontend_bugfixes():
    print("\n[前端 bug 修复]")
    js = os.path.join(ROOT, "frontend", "src", "components", "LogConsole.vue")
    s = open(js, encoding="utf-8").read()
    check("日志粘底用 ref()（生产构建才会生效）", "const el = ref(null)" in s and "let el = null" not in s)
    check("日志滚动读 el.value", "el.value" in s)

    s = open(os.path.join(ROOT, "frontend", "src", "views", "MaterialsView.vue"),
             encoding="utf-8").read()
    check("人设导入按钮指向正确的 ref 名",
          "personaInput.click()" in s and "$refs.personaFile.click()" not in s)

    s = open(os.path.join(ROOT, "frontend", "src", "components", "SideBar.vue"),
             encoding="utf-8").read()
    check("侧栏写作方式映射含 team", 'team: "团队润色"' in s or 'team:"团队润色"' in s)

    # 阶段名统一：素材页的步骤卡要认 chars，别再有阶段漏在映射表外
    for path, needles in (
        ("frontend/src/views/MaterialsView.vue", ['key: "chars"', 'key: "crawl"',
                                                 'key: "filter"', 'key: "distill"']),
        ("frontend/src/components/TaskBar.vue", ['chars: "角色卡"', 'runall: "一键跑素材"']),
    ):
        s = open(os.path.join(ROOT, path), encoding="utf-8").read()
        for n in needles:
            check("{} 认 {}".format(os.path.basename(path), n), n in s)


# ======================================================================
# bug 3：models.distill_map/distill_reduce 走顶层 models 段
# ======================================================================
def test_distill_models():
    print("\n[分阶段模型]")
    import pipeline.distill as distill
    seen = []
    distill.llm_for = lambda model, base=None, providers=None: (
        seen.append(model) or types.SimpleNamespace(model=model or "base"))
    distill.run_map = lambda llm, cfg: 0
    distill.run_reduce = lambda llm, cfg: 0

    # 完整配置形态（main.py 现在传这种）
    seen.clear()
    distill.run_distill({"distill": {"min_text_chars": 100},
                         "models": {"distill_map": "MAP-M", "distill_reduce": "RED-M"}})
    check("完整配置：map/reduce 取到顶层 models", seen == ["MAP-M", "RED-M"], str(seen))

    # 旧形态：distill 子段自带 models（向后兼容）
    seen.clear()
    distill.run_distill({"min_text_chars": 100,
                         "models": {"distill_map": "A", "distill_reduce": "B"}})
    check("兼容子段形态", seen == ["A", "B"], str(seen))

    seen.clear()
    distill.run_distill({"min_text_chars": 100})
    check("都没配则回落主模型", seen == [None, None], str(seen))


# ======================================================================
# bug 4：请求间隔下限不再硬编码
# ======================================================================
def test_interval_floor():
    print("\n[请求间隔下限]")
    import random
    from spider.fetcher import random_interval
    random.seed(7)
    vals = [random_interval((0.1, 0.0), 3.0) for _ in range(50)]
    check("默认下限 3.0 生效", min(vals) >= 3.0, str(min(vals)))
    vals = [random_interval((0.5, 1.5), 0.0) for _ in range(200)]
    check("下限可配 0（不保护）", 0.5 <= min(vals) <= 0.6, str(min(vals)))
    check("上限仍受尊重", max(vals) <= 1.5, str(max(vals)))


# ======================================================================
# config_schema：单一事实来源
# ======================================================================
def test_config_schema():
    print("\n[配置元数据]")
    fields = config_schema.FIELDS
    paths = [f["path"] for f in fields]
    check("字段无重复", len(paths) == len(set(paths)))
    check("字段总数 71", len(fields) == 71, str(len(fields)))
    check("白名单由 schema 派生", set(ALLOWED_CONFIG) == set(paths))
    check("分组齐全", {g["key"] for g in config_schema.fields_json()["groups"]} ==
          {"basic", "crawl", "filter", "distill", "write", "team", "chars",
           "providers", "models"})
    bad = [f["path"] for f in fields if f["type"] not in config_schema.TYPE_MAP]
    check("类型名合法", not bad, str(bad))
    bad = [f["path"] for f in fields if not (f.get("label") and f.get("help"))]
    check("每个字段都有中文标签与说明", not bad, str(bad))
    check("预设档位存在", len(config_schema.PRESETS) == 3)
    for p in config_schema.PRESETS:
        unknown = [k for k in p["values"] if k not in set(paths)]
        check("预设「{}」的键都合法".format(p["label"]), not unknown, str(unknown))
    # 隐藏配置项必须已暴露（此前只能手改 yaml 的那些）
    must = ["write.self_revise", "write.use_personas", "write.persona_char_limit",
            "character_cards.min_mentions", "character_cards.max_articles_per_char",
            "character_cards.concurrency", "crawl.skip_img_posts", "crawl.empty_day_limit",
            "crawl.debug_save_raw", "crawl.min_hot", "crawl.start_date",
            "distill.reduce_batch_size", "distill.batch_char_limit",
            "write.knowledge_char_limit", "write.mode", "write.article_type",
            "write.cp_combo", "write.ending"]
    missing = [k for k in must if k not in set(paths)]
    check("原先只能手改 yaml 的键已全部暴露", not missing, str(missing))


def test_api_config_schema():
    print("\n[/api/config-schema]")
    c = app.test_client()
    j = c.get("/api/config-schema").get_json()
    check("接口可用", len(j["fields"]) == 71)
    check("带分组说明", all(g.get("help") for g in j["groups"]))
    check("带 .env 字段说明", len(j["env"]) == 7)


# ======================================================================
# 新 API：提示词 / 成果文件 / 连通性
# ======================================================================
def test_prompts_api():
    print("\n[/api/prompts]")
    c = app.test_client()
    name = "_t_prompt.md"
    check("新建提示词", c.put("/api/prompts/" + name,
                          json={"content": "你好 $name，$day"}).status_code == 200)
    r = c.put("/api/prompts/" + name, json={"content": "占位符被我删了"})
    check("删除占位符被拒", r.status_code == 400, str(r.get_json()))
    check("报错说清缺了哪些占位符", "$name" in r.get_json()["error"])
    c.put("/api/prompts/" + name, json={"content": "改 $name $day"})
    j = c.get("/api/prompts/" + name).get_json()
    check("改动自动备份", len(j["backups"]) >= 1, str(j["backups"]))
    r = c.post("/api/prompts/" + name + "/restore", json={"backup": j["backups"][0]})
    check("回滚生效", r.status_code == 200 and r.get_json()["content"] == "你好 $name，$day")
    check("目录穿越被拒",
          c.put("/api/prompts/..%2Fconfig.yaml", json={"content": "x"}).status_code in (400, 404))
    os.remove(os.path.join(ROOT, "prompts", name))

    j = c.get("/api/prompts").get_json()
    check("列表含既有模板", any(i["name"] == "write_chapter.md" for i in j["items"]))
    check("提问模板已就位", any(i["name"] == "write_questions.md" for i in j["items"]))
    wc = next(i for i in j["items"] if i["name"] == "write_chapter.md")
    check("write_chapter 占位符齐全（22 个）", len(wc["vars"]) == 22, str(wc["vars"]))


def test_output_api():
    print("\n[/api/output/*]")
    c = app.test_client()
    name = "_t_out.md"
    open(os.path.join(storage.OUTPUT_DIR, name), "w", encoding="utf-8").write("# 测试\n")
    r = c.post("/api/output/" + name + "/rename", json={"to": "_t_out_2"})
    check("重命名", r.status_code == 200 and r.get_json()["name"] == "_t_out_2.md")
    r = c.get("/api/output/_t_out_2.md/export")
    check("导出为附件", r.status_code == 200 and "attachment" in r.headers.get("Content-Disposition", ""))
    check("删除", c.delete("/api/output/_t_out_2.md").status_code == 200)
    check("删除不存在的文件 404", c.delete("/api/output/_nope.md").status_code == 404)
    check("路径穿越被拒",
          c.delete("/api/output/..%2F..%2Fconfig.yaml").status_code in (400, 404))


def test_verify_api():
    print("\n[/api/verify/*]（只要求返回结构化结果，不强求真连通）")
    c = app.test_client()
    for ep in ("/api/verify/llm", "/api/verify/lofter"):
        j = c.post(ep).get_json()
        check("{} 返回结构化结果".format(ep), "ok" in j and "note" in j, str(j))


# ======================================================================
# 写作提问：/api/logs 带待答问题，/api/answer 落盘回答
# ======================================================================
def test_ask_api():
    print("\n[写作问答 /api/answer]")
    import json as _json
    import time as _time
    c = app.test_client()
    ask_dir = os.path.join(storage.DATA_DIR, "ask")
    os.makedirs(ask_dir, exist_ok=True)
    qp = os.path.join(ask_dir, "question.json")
    ap = os.path.join(ask_dir, "answer.json")
    for p in (qp, ap):
        if os.path.exists(p):
            os.remove(p)

    check("没有待答问题时回答被拒",
          c.post("/api/answer", json={"id": "q1", "answers": {}}).status_code == 409)
    with open(qp, "w", encoding="utf-8") as f:
        _json.dump({"id": "q1", "title": "测试", "items": [{"q": "？", "options": [], "suggest": "x"}],
                    "created_at": int(_time.time()), "expires_at": int(_time.time()) + 60}, f)
    j = c.get("/api/logs").get_json()
    check("/api/logs 带出待答问题", j.get("question") and j["question"]["id"] == "q1",
          str(j.get("question")))
    check("id 不匹配被拒", c.post("/api/answer", json={"id": "stale", "answers": {}}).status_code == 409)
    r = c.post("/api/answer", json={"id": "q1", "answers": {"0": "雪夜"}})
    saved = _json.load(open(ap, encoding="utf-8"))
    check("回答落盘", r.status_code == 200 and saved["answers"]["0"] == "雪夜" and saved["id"] == "q1")
    check("问题已清（界面立刻收起）", not os.path.exists(qp))
    os.remove(ap)

    # 过期的问题不该再展示
    with open(qp, "w", encoding="utf-8") as f:
        _json.dump({"id": "q2", "title": "过期", "items": [],
                    "created_at": 0, "expires_at": 1}, f)
    check("过期问题不再展示", c.get("/api/logs").get_json().get("question") is None)
    check("过期问题文件已清理", not os.path.exists(qp))


# ======================================================================
# /api/posts 分类可见 + outputs 分组 + 阶段失败结构化
# ======================================================================
def test_posts_and_groups():
    print("\n[分类可见 / 成果分组 / 失败结构化]")
    storage.ensure_dirs()
    import json as _json
    rows = [
        {"title": "甲", "author": "a", "url": "u1", "post_type": "article",
         "article_type": "单人向", "cp_combo": "微量", "ending": "BE", "hot": 5},
        {"title": "乙", "author": "b", "url": "u2", "post_type": "img",
         "article_type": "CP向", "cp_combo": "男男", "ending": "HE", "hot": 9},
    ]
    with open(storage.FILTERED_JSONL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(_json.dumps(r, ensure_ascii=False) + "\n")
    c = app.test_client()
    j = c.get("/api/posts?kind=filtered").get_json()
    check("列表返回分类", all("category" in it and "ending" in it for it in j["items"]), str(j["items"]))
    check("分类形如「单人向·微量」", j["items"][0]["category"] in ("单人向·微量", "CP向·男男"))
    j = c.get("/api/posts?kind=filtered&article_type=单人向").get_json()
    check("按类型筛选", j["total"] == 1 and j["items"][0]["title"] == "甲", str(j["total"]))
    j = c.get("/api/posts?kind=filtered&q=乙").get_json()
    check("搜索", j["total"] == 1 and j["items"][0]["title"] == "乙")
    j = c.get("/api/posts?kind=filtered&sort=hot&order=desc").get_json()
    check("按热度降序", [it["hot"] for it in j["items"]] == [9, 5], str(j["items"]))
    j = c.get("/api/posts?kind=filtered&sort=hot&order=asc").get_json()
    check("按热度升序", [it["hot"] for it in j["items"]] == [5, 9], str(j["items"]))

    os.makedirs(storage.OUTPUT_DIR, exist_ok=True)
    for fn in ("20260101-000000_正文.md", "20260101-000000_正文_讨论记录.md",
               "提示词_某篇.md"):
        open(os.path.join(storage.OUTPUT_DIR, fn), "w", encoding="utf-8").write("x")
    j = c.get("/api/data").get_json()
    g = j["output_groups"]
    check("成果已分组", g["article"] == ["20260101-000000_正文.md"] and
          len(g["discussion"]) == 1 and len(g["prompt"]) == 1, str(g))

    j = c.get("/api/logs").get_json()
    check("/api/logs 带 stage_result 字段", "stage_result" in j and "elapsed" in j)


def test_asset_read_routes():
    print("\n[知识库/人物卡读取路由]")
    storage.ensure_dirs()
    c = app.test_client()
    os.makedirs(storage.KNOWLEDGE_DIR, exist_ok=True)
    with open(os.path.join(storage.KNOWLEDGE_DIR, "_t_k.md"), "w", encoding="utf-8") as f:
        f.write("# 知识\n")
    check("知识库可读", c.get("/api/file/knowledge/_t_k.md").get_json()["content"] == "# 知识\n")
    os.makedirs(storage.PERSONAS_DIR, exist_ok=True)
    with open(os.path.join(storage.PERSONAS_DIR, "_t_p.md"), "w", encoding="utf-8") as f:
        f.write("# 人设\n")
    check("官方人物卡可读（专用接口）",
          c.get("/api/personas/_t_p.md").get_json()["content"] == "# 人设\n")
    check("人物卡不走 /api/file（旧前端踩过的路由）",
          c.get("/api/file/personas/_t_p.md").status_code == 404)
    os.makedirs(storage.PERSONAS_DISTILLED_DIR, exist_ok=True)
    with open(os.path.join(storage.PERSONAS_DISTILLED_DIR, "_t_c.md"), "w", encoding="utf-8") as f:
        f.write("# 蒸馏卡\n")
    j = c.get("/api/character-cards").get_json()
    check("蒸馏卡列表", any(it["name"] == "_t_c" for it in j["files"]), str(j["files"]))
    check("蒸馏卡按名读取", c.get("/api/character-cards/_t_c").get_json()["content"] == "# 蒸馏卡\n")
    os.remove(os.path.join(storage.KNOWLEDGE_DIR, "_t_k.md"))
    os.remove(os.path.join(storage.PERSONAS_DIR, "_t_p.md"))
    os.remove(os.path.join(storage.PERSONAS_DISTILLED_DIR, "_t_c.md"))


# ======================================================================
# config.yaml 保存保留注释
# ======================================================================
def test_config_comment_preserved():
    print("\n[config.yaml 注释]")
    c = app.test_client()
    backup = open(CONFIG_PATH, encoding="utf-8").read()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write("# 顶层测试注释\ncrawl:\n  tag: 测试tag   # 行内注释\n  max_count: 0\n")
        c.post("/api/config", json={"crawl.max_count": 5})
        out = open(CONFIG_PATH, encoding="utf-8").read()
        check("顶层注释保留", "# 顶层测试注释" in out, out[:120])
        check("行内注释保留", "# 行内注释" in out)
        check("值已更新", "max_count: 5" in out)
    finally:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(backup)


# ======================================================================
# @ 点名正则：前后端必须一致（双写最容易飘）
# ======================================================================
def test_mention_regex_parity():
    print("\n[@ 点名正则前后端一致]")
    py = open(os.path.join(ROOT, "pipeline", "writer.py"), encoding="utf-8").read()
    js = open(os.path.join(ROOT, "frontend", "src", "views", "WriteView.vue"),
              encoding="utf-8").read()
    m_py = re.search(r'_MENTION_RE = re\.compile\(\s*r"(.+?)"\s*\n\s*r"(.+?)"\s*\n\s*r"(.+?)"',
                     py, re.S)
    m_js = re.search(r'MENTION_RE = /(.+?)/g;', js, re.S)
    check("两边都取到了正则", bool(m_py) and bool(m_js))
    # Python 源里写的是 r"...'\"..."（反斜杠转义引号），JS 里是 '"'，语义相同
    py_re = "".join(m_py.groups()).replace('\\"', '"')
    js_re = m_js.group(1)
    check("正则字面一致", py_re == js_re, "\npy: {}\njs: {}".format(py_re, js_re))

    # 行为断言：三种写法都能识别，且取到正确的档位
    import pipeline.writer as writer
    cases = [("@回响", "回响", ""), ("@回响:微量", "回响", "微量"),
             ("@回响（主役）", "回响", "主役"), ("@卡尔·休斯顿:跑龙套", "卡尔·休斯顿", "跑龙套")]
    for text, name, level in cases:
        got = writer._extract_mentions(text)
        check("点名识别 {}".format(text), got == [{"name": name, "level": level or None}],
              str(got))
    got = writer._extract_mentions("@回响:微量", "@回响:主役")
    check("同名取最高档", got[0]["level"] == "主役", str(got))
    # 档位表也要一致
    lv_py = re.search(r'APPEARANCE_LEVELS = \[(.+?)\]', py, re.S).group(1)
    norm = lambda t: [x.strip().strip("\"'") for x in t.split(",") if x.strip()]
    levels = norm(lv_py)
    check("后端档位表是那 5 档", levels == ["跑龙套", "微量", "配角", "重要", "主役"], str(levels))
    missing = [l for l in levels if ('value: "%s"' % l) not in js and ('"%s"' % l) not in js]
    check("前端档位表含同样的 5 档", not missing, str(missing))


# ======================================================================
# 多提供商：resolve_ref 解析 + providerlist 整编 + 脱敏回写
# ======================================================================
def test_multi_provider():
    print("\n[多提供商]")
    from llm.client import resolve_ref, providers_map, llm_for
    provs = [{"name": "deepseek", "base_url": "https://api.deepseek.com/v1",
              "api_key": "sk-ds"}]
    got = resolve_ref("deepseek/deepseek-chat", provs)
    check("提供商/模型 解析", got == ("https://api.deepseek.com/v1", "sk-ds",
                                      "deepseek-chat", "deepseek"), str(got))
    got = resolve_ref("mimo-v2.6-pro", provs)
    check("纯模型名走默认提供商", got == (None, None, "mimo-v2.6-pro", None), str(got))
    got = resolve_ref("deepseek/deepseek-chat", {"deepseek": provs[0]})
    check("dict 形态 providers（手写 yaml）",
          got[0] == "https://api.deepseek.com/v1" and got[3] == "deepseek", str(got))
    got = resolve_ref("ghost/m", provs)
    check("未知提供商整串按模型名", got == (None, None, "ghost/m", None), str(got))

    base = types.SimpleNamespace(model="base-m", label="base-m")
    c2 = llm_for("deepseek/deepseek-chat", base, provs)
    check("llm_for 派生跨提供商客户端",
          c2.base_url == "https://api.deepseek.com/v1" and c2.model == "deepseek-chat"
          and c2.label == "deepseek/deepseek-chat", str(c2.base_url))
    c3 = llm_for("  ", base, provs)
    check("留空复用主客户端", c3 is base)
    got = resolve_ref("deepseek/deepseek-chat", [])
    check("providers 缺失时按整串模型名处理",
          got == (None, None, "deepseek/deepseek-chat", None), str(got))


def test_providerlist_coerce():
    print("\n[providerlist 整编与脱敏回写]")
    from gui.server import _coerce
    out = _coerce([{"name": " ds ", "base_url": " https://x ", "api_key": " sk-real "}],
                  "providerlist")
    check("规范化（去空格）", out == [{"name": "ds", "base_url": "https://x",
                                       "api_key": "sk-real"}], str(out))
    check("空名条目丢弃", _coerce([{"name": "", "base_url": "x"}], "providerlist") == [])
    check("非列表给空", _coerce("x", "providerlist") == [])
    check("手写 dict 形态转列表", _coerce(
        {"ds": {"base_url": "https://x", "api_key": "k"}}, "providerlist") ==
        [{"name": "ds", "base_url": "https://x", "api_key": "k"}])

    c = app.test_client()
    backup = open(CONFIG_PATH, encoding="utf-8").read()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write("providers:\n- name: ds\n  base_url: https://x\n"
                    "  api_key: sk-real-secret\n")
        j = c.get("/api/state").get_json()
        masked = j["config"]["providers"][0]["api_key"]
        check("state 返回脱敏 key", "****" in masked and "sk-real-secret" not in masked,
              masked)
        c.post("/api/config", json={"providers": [
            {"name": "ds", "base_url": "https://y", "api_key": masked}]})
        out = open(CONFIG_PATH, encoding="utf-8").read()
        check("脱敏值回写不丢真 key", "sk-real-secret" in out, out[:200])
        check("同条目其他字段可更新", "https://y" in out)
    finally:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(backup)


# ======================================================================
# 去AI味 skill 加载：三档
# ======================================================================
def test_style_skill():
    print("\n[去AI味 skill]")
    from llm.prompts import load_style_skill
    check("关 = 空", load_style_skill("关") == "")
    core = load_style_skill("精简")
    check("精简含核心规则卡", "假靶子" in core and "一级禁用词" in core, str(len(core)))
    full = load_style_skill("完整")
    check("完整含禁用词表全文", "最毒禁用句式" in full and len(full) > len(core) * 2,
          "len(full)={} len(core)={}".format(len(full), len(core)))
    check("缓存生效", load_style_skill("精简") is core)


# ======================================================================
# 设定/剧情素材库 /api/lore
# ======================================================================
def test_lore_api():
    print("\n[/api/lore]")
    c = app.test_client()
    r = c.post("/api/lore", data={"files": (io.BytesIO("时间线设定".encode("utf-8")),
                                            "时间线.md")},
               content_type="multipart/form-data")
    check("上传", r.status_code == 200 and r.get_json()["saved"] == ["时间线.md"],
          str(r.get_json()))
    j = c.get("/api/lore").get_json()
    check("列表", any(f["rel"] == "时间线.md" for f in j["files"]), str(j["files"]))
    check("读取", c.get("/api/lore/时间线.md").get_json()["content"] == "时间线设定")
    # 子目录与路径安全
    from pipeline import lore as lore_mod
    lore_mod.lore_write("设定/世界观.md", "# 世界观\n")
    rel = next(f["rel"] for f in lore_mod.lore_files() if "世界观" in f["rel"])
    check("子目录可读", c.get("/api/lore/" + rel).status_code == 200)
    check("目录穿越被拒",
          c.get("/api/lore/..%2F..%2Fconfig.yaml").status_code in (400, 404))
    check("删除", c.delete("/api/lore/时间线.md").status_code == 200)
    check("删除后 404", c.get("/api/lore/时间线.md").status_code == 404)
    check("不存在删除 404", c.delete("/api/lore/时间线.md").status_code == 404)
    lore_mod.lore_delete("设定/世界观.md")


if __name__ == "__main__":
    try:
        test_frontend_bugfixes()
        test_distill_models()
        test_interval_floor()
        test_multi_provider()
        test_providerlist_coerce()
        test_style_skill()
        test_config_schema()
        test_api_config_schema()
        test_prompts_api()
        test_output_api()
        test_verify_api()
        test_ask_api()
        test_posts_and_groups()
        test_asset_read_routes()
        test_lore_api()
        test_config_comment_preserved()
        test_mention_regex_parity()
        print("\nGUI 回归测试全部通过（{} 项断言）".format(len(_ok)))
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)   # 只清临时沙盒

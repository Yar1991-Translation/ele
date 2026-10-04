# -*- coding: utf-8 -*-
"""写作流程离线自测：FakeLLM 走完 骨架→大纲→逐章→自查→末章统筹→结局校验。

必须在 import spider.storage 之前设好 DISTILLER_DATA_DIR，全程只在临时沙盒里读写。
运行：python -m tests.test_write_flow
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time

SANDBOX = tempfile.mkdtemp(prefix="write_flow_")
os.environ["DISTILLER_DATA_DIR"] = SANDBOX        # 必须早于 storage 的 import
os.environ["DISTILLER_ASK_MODE"] = "auto"         # 测试永不阻塞等输入

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.writer import write_article          # noqa: E402
from spider import storage                         # noqa: E402
from llm.prompts import load_prompt                # noqa: E402


def _spine_obj():
    return {"premise": "失忆开篇，死亡收尾", "core_conflict": "他必须想起来",
            "start_state": "失忆", "end_state": "死亡",
            "key_scenes": [{"name": "醒来", "who": "回响、蜂医", "where": "医疗舱",
                            "what": "他不记得自己是谁", "why_key": "开篇"}]}


def _outline_obj():
    return {"title": "测试文章", "premise": "一段话",
            "chapters": [{"title": "第一章", "summary": "醒来",
                          "beats": ["他醒来"], "covers": [1, 3],
                          "scenes": [{"place": "医疗舱", "time": "清晨",
                                      "people": "回响", "event": "睁眼"}],
                          "tropes_used": []},
                         {"title": "第二章", "summary": "死去",
                          "beats": ["他死去"], "covers": [2],
                          "scenes": [{"place": "水下", "time": "夜里",
                                      "people": "回响", "event": "沉下去"}],
                          "tropes_used": []}]}


class FakeLLM:
    """按提示词内容分发假结果；记录调用顺序供断言。"""
    model = "fake"
    label = "fake"

    def __init__(self, match=True):
        self.match = match
        self.calls = []
        self.users = []   # 全部 user 提示词原文（quick 模式等场景做内容断言用）

    def chat_messages(self, messages, **kw):
        """多轮对话（章节查询循环用）：桩实现只看 system 与最后一条 user。"""
        return self.chat(messages[0]["content"], messages[-1]["content"], **kw)

    def chat(self, system, user, **kw):
        self.users.append(user)
        self.calls.append(("chat", system[:30]))
        if "修订后的末章全文" in system:
            return "【末章统筹版】\n\n" + "他关掉手电，回身看了一眼。" * 20
        if "修订后的本章全文" in system:
            return "【修订版】\n\n" + "他把耳机塞回耳朵。" * 20
        # 设计阶段走多轮循环后由 chat 落地：骨架/大纲 JSON（与 chat_json 同一套分发）
        if "只输出 JSON" in system and '"chapters"' in user:
            return json.dumps(_outline_obj(), ensure_ascii=False)
        if "只输出 JSON" in system and '"key_scenes"' in user:
            return json.dumps(_spine_obj(), ensure_ascii=False)
        return "【正文】\n\n" + "他站起来，推开门。" * 30

    def chat_json(self, system, user, **kw):
        self.users.append(user)
        self.calls.append(("json", system[:30]))
        # 提问策略：基类不提问（问题走 system 判别，不受用户文本影响）
        if "提问策略师" in system:
            return {"questions": []}
        # 判定顺序：需求拆解/兑现核对的提示词别撞上大纲、骨架的判别串
        if "契约，不是创作" in user:
            return {"items": [
                {"id": 1, "kind": "情节", "req": "以失忆开篇"},
                {"id": 2, "kind": "情节", "req": "以死亡收尾"},
                {"id": 3, "kind": "基调", "req": "短句为主"},
            ]}
        if "兑现情况" in user:
            return {"items": [
                {"id": 1, "hit": True, "note": "开篇即失忆"},
                {"id": 2, "hit": self.match, "note": "结尾他沉下去了"},
                {"id": 3, "hit": True, "note": "通篇短句"},
            ], "summary": "整体符合想法"}
        # 先判大纲：大纲提示词里嵌着骨架 JSON，含 "key_scenes"，不能误判成骨架
        if '"chapters"' in user:
            return _outline_obj()
        if '"key_scenes"' in user:
            return _spine_obj()
        if "连续性事实" in user:
            return {"facts": ["回响在医疗舱醒来时失去了记忆"]}
        if "实际结局走向" in user:
            return {"actual": "BE", "match": self.match, "note": "结尾他沉下去了"}
        raise AssertionError("FakeLLM 收到无法识别的 chat_json：" + user[:120])


def _prepare_sandbox():
    storage.ensure_dirs()
    os.makedirs(os.path.join(storage.KNOWLEDGE_DIR, "单人向·微量"), exist_ok=True)
    for name in ("文风", "人设与关系", "桥段与爽点", "雷点"):
        with open(os.path.join(storage.KNOWLEDGE_DIR, "单人向·微量", name + ".md"),
                  "w", encoding="utf-8") as f:
            f.write("# %s\n\n- 短句为主。" % name)
    with open(os.path.join(storage.PERSONAS_DIR, "回响.md"), "w", encoding="utf-8") as f:
        f.write("# 回响\n\n前潜艇声呐兵，嘴欠，戴耳机。")


def _run(match=True):
    _prepare_sandbox()
    # 章节体量刻意调小（400/200 -> 2 章）：FakeLLM 的假正文约 270 字，
    # 不会触发「过短重写」的返工分支，调用次数才可控
    cfg = {"write": {"length": 400, "chapter_chars": 200, "self_revise": True,
                     "final_pass": True, "ending_check": True,
                     "use_personas": True, "persona_char_limit": 4000},
           "models": {}}
    fake = FakeLLM(match=match)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path = write_article("@回响:主役", cfg, llm=fake,
                             article_type="单人向", cp_combo="微量", ending="BE")
    return path, fake, buf.getvalue()


def test_full_flow():
    path, fake, out = _run()
    assert os.path.exists(path), "没有产出文件"
    text = open(path, encoding="utf-8").read()
    assert "测试文章" in text and "【修订版】" in text, "正文没有落盘（自查修订版应进正文）"
    assert "# 进度：章节 2/2" in out, "缺章节进度标记：\n" + out
    assert "# 进度：统筹 1/1" in out, "缺末章统筹标记：\n" + out
    assert "# 进度：校验 1/1" in out, "缺结局校验标记：\n" + out
    assert "结局校验通过" in out, "结局校验没跑完：\n" + out
    assert "末章已统筹" in out, "末章统筹没生效：\n" + out
    assert "【末章统筹版】" in text, "统筹后的末章没写进正文"
    assert "⚠ 结局走向校验" not in text, "对齐时不应写警告头"
    assert "想法兑现清单" in text, "文首应有想法兑现清单"
    assert "✓ [情节] 以失忆开篇" in text, "兑现项要逐条上墙"
    assert "想法兑现：3/3" in out, "想法校验没跑完：\n" + out
    assert "章节安排" in out, "大纲没有打进日志：\n" + out
    kinds = [k for k, _ in fake.calls]
    assert kinds.count("chat") == 2 * 2 + 1 + 2, "调用次数不对（含骨架/大纲各1次设计调用）：{}".format(kinds)
    print("test_full_flow OK")
    print("  文件：", os.path.basename(path))
    print("  日志片段：", " | ".join(l for l in out.splitlines() if "进度" in l or "校验" in l))


def test_ending_mismatch():
    path, _, out = _run(match=False)
    text = open(path, encoding="utf-8").read()
    assert "⚠ 结局走向校验" in text, "结局不符时文首必须有标注"
    assert "✓ 结局走向校验" not in text, "没修好不能写成功标记"
    assert "结局校验未通过" in out
    assert "自动修复一次收尾" in out, "不符时应先尝试自动修复：\n" + out
    assert "✗ [情节] 以死亡收尾" in text, "未兑现的需求要在清单里点名"
    assert "想法兑现：2/3" in out
    print("test_ending_mismatch OK")


class ShortThenLong(FakeLLM):
    """正文首版故意过短，返工版正常——测「过短章节重写」分支。"""

    def chat(self, system, user, **kw):
        if "文笔出色的同人作者" in system:
            self.calls.append(("chat", "short" if "返工要求" not in user else "retry"))
            return "太短" if "返工要求" not in user else \
                "【正文】\n\n" + "他站起来，推开门。" * 30
        return super().chat(system, user, **kw)


def test_short_chapter_retry():
    _prepare_sandbox()
    cfg = {"write": {"length": 400, "chapter_chars": 200, "self_revise": False,
                     "final_pass": False, "ending_check": False,
                     "use_personas": True, "persona_char_limit": 4000},
           "models": {}}
    fake = ShortThenLong()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path = write_article("@回响:主役", cfg, llm=fake,
                             article_type="单人向", cp_combo="微量", ending="不限")
    out = buf.getvalue()
    text = open(path, encoding="utf-8").read()
    assert "过短" in out and "重写后约" in out, "没走重写分支：\n" + out
    kinds = [k for k, _ in fake.calls]
    assert kinds.count("chat") == 4 + 2, "两章各写一次+返工一次+设计2次：{}".format(kinds)
    assert "太短" not in text, "返工成功后不该留着过短版"
    assert "【正文】" in text
    assert "想法兑现清单" in text
    print("test_short_chapter_retry OK")


class AskFakeLLM(FakeLLM):
    """两个检查点各抛一个问题，测「提问 -> 自动应答 -> 答案进上下文/文首」。"""

    def chat_json(self, system, user, **kw):
        if "提问策略师" in system:
            self.calls.append(("json", "ask"))
            if "想法澄清" in user:
                return {"questions": [
                    {"q": "重逢放在雨夜还是雪夜？", "options": ["雨夜", "雪夜"],
                     "suggest": "雨夜"}]}
            return {"questions": [
                {"q": "结尾要留希望吗？", "options": ["留一线希望", "彻底断绝"],
                 "suggest": "留一线希望"}]}
        return super().chat_json(system, user, **kw)


def test_ask_flow():
    _prepare_sandbox()
    cfg = {"write": {"length": 400, "chapter_chars": 200, "self_revise": False,
                     "final_pass": False, "ending_check": True, "idea_check": True,
                     "ask_enabled": True, "ask_max": 3, "ask_timeout": 30,
                     "use_personas": True, "persona_char_limit": 4000},
           "models": {}}
    fake = AskFakeLLM()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path = write_article("@回响:主役", cfg, llm=fake,
                             article_type="单人向", cp_combo="微量", ending="BE")
    out = buf.getvalue()
    text = open(path, encoding="utf-8").read()
    assert "创作问答" in text, "文首应有创作问答记录"
    assert "雨夜" in text and "留一线希望" in text, "建议答案要进问答记录"
    assert "（你的回答" not in text.replace("（你的回答）", ""), "auto 模式不该冒充用户回答"
    assert "自动应答" in out, "auto 模式日志要说明是自动应答：\n" + out
    kinds = [k for k, _ in fake.calls]
    assert kinds.count("chat") == 2 + 2, "两章正文 + 设计 2 次：{}".format(kinds)
    print("test_ask_flow OK")


def test_ask_file_mode():
    from pipeline import ask_user
    os.environ["DISTILLER_ASK_MODE"] = "file"
    try:
        sess = ask_user.AskSession({"ask_enabled": True, "ask_max": 5, "ask_timeout": 20})

        def _answer():
            for _ in range(100):
                if os.path.exists(ask_user.Q_PATH):
                    data = json.load(open(ask_user.Q_PATH, encoding="utf-8"))
                    json.dump({"id": data["id"], "skip": False,
                               "answers": {"0": "雪夜"}},
                              open(ask_user.A_PATH, "w", encoding="utf-8"))
                    return
                time.sleep(0.1)

        t = threading.Thread(target=_answer)
        t.start()
        rows = sess.ask("测试", [{"q": "雨夜还是雪夜？", "options": ["雨夜", "雪夜"],
                                 "suggest": "雨夜"}])
        t.join()
        assert rows == [("雨夜还是雪夜？", "雪夜", "你的回答")], rows
        assert not os.path.exists(ask_user.Q_PATH), "答完要清理问题文件"
    finally:
        os.environ["DISTILLER_ASK_MODE"] = "auto"
    print("test_ask_file_mode OK")


def test_ask_timeout():
    from pipeline import ask_user
    os.environ["DISTILLER_ASK_MODE"] = "file"
    try:
        sess = ask_user.AskSession({"ask_enabled": True, "ask_max": 5, "ask_timeout": 1})
        rows = sess.ask("超时测试", [{"q": "A还是B？", "options": ["A", "B"],
                                     "suggest": "A"}])
        assert rows == [("A还是B？", "A", "超时未答，按建议")], rows
        assert not os.path.exists(ask_user.Q_PATH), "超时要清理问题文件"
    finally:
        os.environ["DISTILLER_ASK_MODE"] = "auto"
    print("test_ask_timeout OK")


def test_ask_budget():
    from pipeline.ask_user import AskSession
    sess = AskSession({"ask_enabled": True, "ask_max": 1, "ask_timeout": 30})
    sess.mode = "auto"
    rows = sess.ask("预算", [{"q": "一？", "suggest": "x"}, {"q": "二？", "suggest": "y"}])
    assert len(rows) == 1, "预算只允许一题：{}".format(rows)
    assert sess.ask("预算", [{"q": "三？", "suggest": "z"}]) == [], "预算耗尽不再提问"
    sess2 = AskSession({"ask_enabled": False, "ask_max": 5, "ask_timeout": 30})
    assert sess2.ask("禁用", [{"q": "？", "suggest": "x"}]) == [], "禁用时全程静默"
    print("test_ask_budget OK")


class QueryingLLM(FakeLLM):
    """每章动笔前先查一轮资料——测章节查询循环（lore 工具）。"""

    def chat(self, system, user, **kw):
        if "文笔出色的同人作者" in system:
            if user.startswith("查询结果"):
                self.calls.append(("chat", "after-query"))
                return "【正文】\n\n" + "他站起来，推开门。" * 30
            self.calls.append(("chat", "query"))
            return '{"queries": [{"type": "设定", "name": "时间线.md"}]}'
        return super().chat(system, user, **kw)


def test_query_tool_loop():
    _prepare_sandbox()
    lore_dir = os.path.join(storage.DATA_DIR, "lore")
    os.makedirs(lore_dir, exist_ok=True)
    with open(os.path.join(lore_dir, "时间线.md"), "w", encoding="utf-8") as f:
        f.write("战前->沉船->救援。")
    cfg = {"write": {"length": 400, "chapter_chars": 200, "self_revise": False,
                     "final_pass": False, "ending_check": False,
                     "use_personas": True, "persona_char_limit": 4000,
                     "query_tools": True, "query_rounds": 2},
           "models": {}}
    fake = QueryingLLM()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path = write_article("@回响:主役", cfg, llm=fake,
                             article_type="单人向", cp_combo="微量", ending="不限")
    out = buf.getvalue()
    text = open(path, encoding="utf-8").read()
    assert "查询工具：已启用" in out, "查询工具没启用：\n" + out
    assert "备料查询 1 条" in out, "查询循环没跑：\n" + out
    kinds = [k for k, _ in fake.calls]
    assert kinds.count("chat") == 2 * 2 + 2, "每章 1 查询 1 落笔 + 设计 2 次：{}".format(kinds)
    assert "【正文】" in text
    print("test_query_tool_loop OK")


def test_style_skill_levels():
    _prepare_sandbox()
    base_cfg = {"length": 400, "chapter_chars": 200, "self_revise": False,
                "final_pass": False, "ending_check": False,
                "use_personas": True, "persona_char_limit": 4000,
                "query_tools": False}
    captured = []

    class CaptureLLM(FakeLLM):
        def chat(self, system, user, **kw):
            if "文笔出色的同人作者" in system:
                captured.append(user)
            return super().chat(system, user, **kw)

    # 关：提示词不含规范
    captured.clear()
    cfg = {"write": {**base_cfg, "style_skill": "关"}, "models": {}}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        write_article("@回响:主役", cfg, llm=CaptureLLM(),
                      article_type="单人向", cp_combo="微量", ending="不限")
    assert captured and all("去AI味写作规范" not in u for u in captured), \
        "关档不应注入规范"

    # 精简：每章提示词注入核心规则卡
    captured.clear()
    cfg = {"write": {**base_cfg, "style_skill": "精简"}, "models": {}}
    with contextlib.redirect_stdout(buf):
        write_article("@回响:主役", cfg, llm=CaptureLLM(),
                      article_type="单人向", cp_combo="微量", ending="不限")
    assert captured and all("假靶子" in u for u in captured), \
        "精简档应把核心规则卡注入每章提示词"
    print("test_style_skill_levels OK")


def test_quick_mode():
    _prepare_sandbox()
    with open(os.path.join(storage.PERSONAS_DIR, "红狼.md"), "w", encoding="utf-8") as f:
        f.write("# 红狼\n\n队长。")
    with open(os.path.join(storage.PERSONAS_DIR, "PTSD状况卡.md"), "w", encoding="utf-8") as f:
        f.write("# PTSD\n\n症状素材库。")
    cfg = {"write": {"length": 400, "chapter_chars": 200, "self_revise": False,
                     "final_pass": False, "ending_check": False,
                     "use_personas": True, "persona_char_limit": 4000,
                     "query_tools": False},
           "models": {}}
    fake = FakeLLM()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path = write_article("@回响:主役 回忆", cfg, llm=fake,
                             article_type="单人向", cp_combo="微量", ending="不限",
                             mode="quick", roster_all=True)
    out = buf.getvalue()
    text = open(path, encoding="utf-8").read()
    assert "方式：关键词速写" in out, "日志方式名应为关键词速写：\n" + out
    assert "关键词速写" in text, "文首 header 应显示关键词速写"
    joined = "\n".join(fake.users)
    assert "【主题关键词】@回响:主役 回忆" in joined, "关键词行没进提示词"
    assert "全员登场" in joined and "@红狼:跑龙套" in joined, "全员跑龙套行没进提示词"
    assert "@PTSD:跑龙套" not in joined, "状况卡不应进全员名单"
    assert "【阵容规定" in joined, "阵容规定没进提示词"
    # 已点名的回响不该再出现跑龙套重复点名
    assert "@回响:跑龙套" not in joined, "已点名角色被重复注入"
    # 故事方向提案：想法澄清的提问标签带 quick 指示
    assert any("故事方向提案" in u for u in fake.users), "quick 模式缺方向提案指示"
    print("test_quick_mode OK")


def test_quality_clauses():
    """写作质量条款防回退：心理落点/禁档案复述/桥段库翻转要在模板里。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wc = open(os.path.join(root, "prompts", "write_chapter.md"), encoding="utf-8").read()
    assert "心理落点" in wc and "禁止档案复述" in wc, "write_chapter 缺质量条款"
    assert "怎么发生的" in wc, "write_chapter 缺 beats 深度条款"
    ol = open(os.path.join(root, "prompts", "write_outline.md"), encoding="utf-8").read()
    assert "不是情节仓库" in ol and "内心事件" in ol, "write_outline 缺质量条款"
    sp = open(os.path.join(root, "prompts", "write_spine.md"), encoding="utf-8").read()
    assert "新在哪里" in sp and "内心场面" in sp, "write_spine 缺质量条款"
    sr = open(os.path.join(root, "prompts", "self_revise.md"), encoding="utf-8").read()
    assert "心理落点是否到位" in sr and "复述人物卡" in sr, "self_revise 缺质量条款"
    print("test_quality_clauses OK")


def test_rating_override():
    """分级达标自动换模型：达标全流程切换、未达标不切换、开关关闭不切换。"""
    from pipeline.writer import rating_override
    mcfg = {"rating_switch": "r16", "rating_model": "grok/grok-4.6"}
    assert rating_override(mcfg, "r16") == "grok/grok-4.6"
    assert rating_override(mcfg, "r18g") == "grok/grok-4.6"
    assert rating_override(mcfg, "r12") == ""
    assert rating_override({"rating_switch": "", "rating_model": "x"}, "r18") == ""
    assert rating_override({"rating_switch": "r16", "rating_model": ""}, "r16") == ""

    _prepare_sandbox()
    cfg = {"write": {"length": 400, "chapter_chars": 200, "self_revise": False,
                     "final_pass": False, "ending_check": False,
                     "use_personas": True, "persona_char_limit": 4000,
                     "query_tools": False},
           "models": {"rating_switch": "r16", "rating_model": "grok/grok-4.6"}}
    seen = []
    import pipeline.writer as writer
    real_llm_for = writer.llm_for

    def fake_llm_for(model, base=None, providers=None):
        seen.append(model)
        return base

    writer.llm_for = fake_llm_for
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            write_article("测试", cfg, llm=FakeLLM(),
                          article_type="单人向", cp_combo="微量", ending="不限",
                          rating="r16")
        assert seen and all(m == "grok/grok-4.6" for m in seen), seen
        assert "本次写作改用 grok/grok-4.6" in buf.getvalue(), buf.getvalue()
        # R12 未达标：全部走各自配置（此处为空=主模型）
        seen.clear()
        cfg2 = {"write": dict(cfg["write"]), "models": dict(cfg["models"])}
        with contextlib.redirect_stdout(buf):
            write_article("测试", cfg2, llm=FakeLLM(),
                          article_type="单人向", cp_combo="微量", ending="不限",
                          rating="r12")
        assert seen and all(m is None for m in seen), seen
    finally:
        writer.llm_for = real_llm_for
    print("test_rating_override OK")


class DesignLLM(FakeLLM):
    """设计阶段先查一次知识库再出设计——测骨架/大纲的素材阅读工具。"""

    def chat_messages(self, messages, **kw):
        sys_txt = messages[0]["content"]
        last = messages[-1]["content"]
        if "资深同人作者兼策划" in sys_txt:
            full = "\n".join(m["content"] for m in messages)
            self.users.append(last)
            if "查询结果" not in last and "查询机会已用完" not in last:
                self.calls.append(("chat", "design-query"))
                return '{"queries": [{"type": "知识库", "name": "文风"}]}'
            self.calls.append(("chat", "outline" if '"chapters"' in full else "spine"))
            return json.dumps(_outline_obj() if '"chapters"' in full else _spine_obj(),
                              ensure_ascii=False)
        return super().chat_messages(messages, **kw)


def test_design_queries():
    _prepare_sandbox()
    with open(os.path.join(storage.PERSONAS_DIR, "红狼.md"), "w", encoding="utf-8") as f:
        f.write("# 红狼\n\n队长，简短行动派。")
    base = {"length": 400, "chapter_chars": 200, "self_revise": False,
            "final_pass": False, "ending_check": False,
            "use_personas": True, "persona_char_limit": 4000,
            "query_tools": True, "query_rounds": 2}
    buf = io.StringIO()

    # 开：骨架/大纲走查询循环，提示词不含知识库全文，配角卡只留名单
    fake = DesignLLM()
    cfg = {"write": {**base, "query_design": True}, "models": {}}
    with contextlib.redirect_stdout(buf):
        path = write_article("@回响:主役 @红狼:配角", cfg, llm=fake,
                             article_type="单人向", cp_combo="微量", ending="不限")
    spine_users = [u for u in fake.users if '"key_scenes"' in u
                   and "查询结果" not in u and "查询机会" not in u]
    assert spine_users, "没捕获到骨架提示词"
    assert "知识库未整段注入" in spine_users[0], "骨架提示词应使用轻量知识库索引"
    assert "单人向·微量·文风" in spine_users[0], "索引应列出可查知识库文件"
    assert "=== 单人向·微量 · 文风 ===" not in spine_users[0],         "知识库全文不应再整段注入（注入头是整段注入特有的）"
    assert "红狼〔配角〕" in spine_users[0], "配角卡应瘦身为名单"
    assert "队长，简短行动派" not in spine_users[0], "配角卡全文不应注入"
    assert "前潜艇声呐兵" in spine_users[0], "主役卡应保留全文"
    result_users = [u for u in fake.users if u.startswith("查询结果")]
    assert any("【知识库/" in u and "短句为主" in u for u in result_users), \
        "知识库查询结果应回填给模型"
    assert os.path.exists(path)
    kinds = [k for k, _ in fake.calls]
    assert [lbl for _, lbl in fake.calls].count("design-query") == 2, "骨架+大纲各一轮备料查询：" + str(fake.calls)

    # 关：行为回到现状（知识库全文在场，无备料查询）
    fake2 = FakeLLM()
    cfg2 = {"write": {**base, "query_design": False}, "models": {}}
    with contextlib.redirect_stdout(buf):
        write_article("@回响:主役 @红狼:配角", cfg2, llm=fake2,
                      article_type="单人向", cp_combo="微量", ending="不限")
    spine2 = [u for u in fake2.users if '"key_scenes"' in u]
    assert spine2 and "短句为主" in spine2[0], "关闭后知识库应整段注入"
    assert all("知识库未整段注入" not in u for u in fake2.users)
    assert not any(lbl == "design-query" for _, lbl in fake2.calls)
    print("test_design_queries OK")


def test_writer_helpers():
    from pipeline.writer import _cap_bible, _ending_window, _story_map

    body = "头" * 5000 + "中" * 20000 + "尾" * 5000
    w = _ending_window(body)
    assert w.startswith("头" * 4000) and w.endswith("尾" * 5000), "长文必须带上结尾"
    assert "[……中段略……]" in w and "头" * 4001 not in w, "中段该被折叠"
    assert _ending_window("短稿") == "短稿"

    m = _story_map([{"title": "A", "summary": "甲"}, {"title": "B", "summary": "乙"}], 2)
    assert "【已写完】" in m and "【正在写这章】" in m and "【待写】" not in m, m

    lines = ["· %d" % i for i in range(200)]
    capped = _cap_bible(lines)
    assert len(capped) < 200 and capped[0] == "· 0" and capped[-1] == "· 199"
    print("test_writer_helpers OK")


def test_prompt_templates():
    common = dict(idea="想法", title="标题", knowledge="知识库", target_type="单人向",
                  cp_combo="微量", ending_text="结局走向：BE", type_hint="要求",
                  personas="人设", plot_anchor="锚", chapter_json="{}", bible="档案",
                  requirements="需求清单", style_skill="去AI味规范",
                  rating_note="R16（辅导级）")
    load_prompt("write_chapter", chapter_no="1", total_chapters="2", chapter_chars="2000",
                size_anchor="锚", prev_tail="尾", prev_head="头", story_map="全篇安排",
                lore_tools="查询工具说明",
                **common)
    load_prompt("write_spine", length="8000", draft="（无原稿）",
                knowledge_source="来源", lore_tools="素材索引",
                **{k: v for k, v in common.items() if k not in ("title", "plot_anchor",
                                                                "chapter_json", "bible")})
    load_prompt("write_outline", length="8000", n_chapters="4", chapter_chars="2000",
                spine="骨架", story_map="安排", knowledge_source="来源",
                lore_tools="素材索引", **common)
    load_prompt("write_expand_outline", length="8000", n_chapters="4", chapter_chars="2000",
                spine="骨架", draft="原稿", knowledge_source="来源",
                lore_tools="素材索引", **common)
    load_prompt("final_pass", total_chapters="2", chapter_text="末章",
                story_so_far="脉络", **common)
    load_prompt("ending_fix", verdict_note="审稿意见", chapter_text="末章",
                story_so_far="脉络", total_chapters="2", **common)
    load_prompt("self_revise", chapter_text="本章", **common)
    load_prompt("team_review", member="文风编辑", round="1", perspective="看文风",
                thinking_note="", prev="（首位）", article="全文", idea="想法",
                knowledge="知识库", personas="人设", style_skill="规范",
                rating_note="R16（辅导级）")
    load_prompt("team_revise", round="1", article="全文",
                reviews="[]", knowledge_source="来源",
                **{k: v for k, v in common.items()
                   if k not in ("plot_anchor", "chapter_json", "bible", "title")})
    load_prompt("write_requirements", idea="想法", target_type="单人向", type_hint="要求")
    load_prompt("idea_check", requirements="清单", story_map="安排", story="正文")
    load_prompt("ending_check", ending="BE", story="正文")
    load_prompt("polish", part_note="", prev_tail="尾", draft="原稿", style_skill="去AI味规范",
                rating_note="R16（辅导级）",
                idea="想法", target_type="单人向", cp_combo="微量",
                ending_text="结局走向：BE", type_hint="要求", personas="人设", knowledge="知识库")
    print("test_prompt_templates OK")


def test_rating_flow():
    """分级：注入提示词、默认兜底 R12、header 标注。"""
    _prepare_sandbox()
    base_cfg = {"length": 400, "chapter_chars": 200, "self_revise": False,
                "final_pass": False, "ending_check": False,
                "use_personas": True, "persona_char_limit": 4000,
                "query_tools": False}
    captured = []

    class CaptureLLM(FakeLLM):
        def chat(self, system, user, **kw):
            if "文笔出色的同人作者" in system:
                captured.append(user)
            return super().chat(system, user, **kw)

    # 指定 r16：逐章提示词带分级边界，文首标注 R16
    captured.clear()
    cfg = {"write": {**base_cfg, "rating": "r16"}, "models": {}}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path = write_article("测试", cfg, llm=CaptureLLM(),
                             article_type="单人向", cp_combo="微量", ending="不限")
    assert captured and all("R16（辅导级）" in u for u in captured), "r16 注入缺失"
    assert "分级：R16（辅导级）" in open(path, encoding="utf-8").read(), "header 缺分级"

    # 不指定：兜底 R12
    captured.clear()
    cfg = {"write": {**base_cfg}, "models": {}}
    with contextlib.redirect_stdout(buf):
        path = write_article("测试", cfg, llm=CaptureLLM(),
                             article_type="单人向", cp_combo="微量", ending="不限")
    assert captured and all("R12（普遍级·全年龄）" in u for u in captured), "默认应兜底 R12"
    assert "分级：R12（普遍级）" in open(path, encoding="utf-8").read()
    # 非法值兜底 R12
    from pipeline.writer import resolve_rating
    assert resolve_rating("xxx", {}) == "r12" and resolve_rating(None, {"rating": "r18"}) == "r18"
    # r18/r18g：无限制模式
    from pipeline.writer import RATING_NOTES, RATING_LABELS
    assert "无限制模式" in RATING_NOTES["r18"] and "无限制模式" in RATING_NOTES["r18g"]
    assert "未成年" in RATING_NOTES["r18"] and "未成年" in RATING_NOTES["r18g"]
    assert RATING_LABELS["r18"] == "R18（无限制）"
    captured.clear()
    cfg = {"write": {**base_cfg, "rating": "r18"}, "models": {}}
    with contextlib.redirect_stdout(buf):
        path = write_article("测试", cfg, llm=CaptureLLM(),
                             article_type="单人向", cp_combo="微量", ending="不限")
    assert captured and all("无限制模式" in u for u in captured), "r18 应注入无限制模式文本"
    assert "分级：R18（无限制）" in open(path, encoding="utf-8").read()
    print("test_rating_flow OK")


if __name__ == "__main__":
    try:
        test_prompt_templates()
        test_full_flow()
        test_ending_mismatch()
        test_short_chapter_retry()
        test_query_tool_loop()
        test_style_skill_levels()
        test_quick_mode()
        test_quality_clauses()
        test_rating_flow()
        test_rating_override()
        test_design_queries()
        test_ask_flow()
        test_ask_file_mode()
        test_ask_timeout()
        test_ask_budget()
        test_writer_helpers()
        print("\n写作流程离线自测全部通过")
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)   # 只清临时沙盒

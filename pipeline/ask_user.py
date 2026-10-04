"""写作途中的提问会话：LLM 有问题 -> 暂停等用户回答 -> 答案交回生成流程。

三种运行模式（AskSession 自动识别）：
- file   GUI 子进程：问题写 data/ask/question.json，轮询 answer.json（带超时）；
         界面在任务条上展示问题并把回答写回 answer.json。
- stdin  命令行直跑：直接在终端问答（一直等你）。
- auto   非交互环境（测试/管道）：不打扰，按模型给的默认建议继续。

回答语义：用户说什么就是什么；没答（超时/跳过/空回车）用问题自带的 suggest。
所有模式共享预算：ask_max 限制每篇最多问几题，问完就不再打扰。
"""
import json
import os
import sys
import time
import uuid

from spider import storage

ASK_DIR = os.path.join(storage.DATA_DIR, "ask")
Q_PATH = os.path.join(ASK_DIR, "question.json")
A_PATH = os.path.join(ASK_DIR, "answer.json")
POLL_SEC = 2.0

# 来源标记：写进日志和文首问答记录，用户能看出哪条是自己答的、哪条是兜底
SRC_USER = "你的回答"
SRC_SUGGEST = "未作答，按建议"
SRC_TIMEOUT = "超时未答，按建议"
SRC_SKIP = "跳过，按建议"


def _detect_mode():
    forced = (os.environ.get("DISTILLER_ASK_MODE") or "").strip().lower()
    if forced in ("file", "stdin", "auto"):
        return forced
    if os.environ.get("DISTILLER_ASK_GUI") == "1":
        return "file"
    try:
        if sys.stdin.isatty():
            return "stdin"
    except Exception:  # noqa: BLE001 拿不到就当非交互
        pass
    return "auto"


class AskSession:
    """一次写作运行的问答会话：带预算，可关（ask_enabled=False 全程静默）。"""

    def __init__(self, cfg_write=None):
        cfg_write = cfg_write or {}
        self.enabled = bool(cfg_write.get("ask_enabled", True))
        self.budget = max(0, int(cfg_write.get("ask_max", 3) or 0))
        self.timeout = max(0, int(cfg_write.get("ask_timeout", 300) or 0))
        self.mode = _detect_mode()
        self.qa_log = []      # [(question, answer, source)] 供文首「创作问答」
        if self.enabled and self.mode == "auto":
            print("  （非交互环境：写作中的提问会按建议自动继续）")

    @property
    def remaining(self):
        return self.budget if self.enabled else 0

    def ask(self, title, questions):
        """暂停等用户回答一批问题。

        questions: [{"q", "options": [...], "suggest": "..."}]
        返回 [(question, answer, source)]；预算耗尽/禁用/无问题 -> 空列表。
        """
        qs = [q for q in (questions or []) if str(q.get("q") or "").strip()]
        if not self.enabled or not qs:
            return []
        qs = qs[: self.budget]
        self.budget -= len(qs)
        if self.mode == "file":
            rows = self._ask_file(title, qs)
        elif self.mode == "stdin":
            rows = self._ask_stdin(title, qs)
        else:
            rows = [(q["q"], q.get("suggest") or "（无）", SRC_SUGGEST) for q in qs]
            for q, a, _src in rows:
                print("  自动应答：{} -> {}".format(q, a))
        self.qa_log += rows
        return rows

    # ------------------------------------------------------------------
    def _ask_file(self, title, qs):
        os.makedirs(ASK_DIR, exist_ok=True)
        for p in (A_PATH,):                       # 清掉上一轮的残留答案
            try:
                os.remove(p)
            except OSError:
                    pass
        qid = "{}-{}".format(time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])
        payload = {
            "id": qid, "title": title,
            "items": [{"q": q["q"], "options": q.get("options") or [],
                       "suggest": q.get("suggest") or ""} for q in qs],
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.timeout if self.timeout else None,
        }
        with open(Q_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        self._print_qs(title, qs)
        print("  已发到任务条，等待你的回答（超时 {} 按建议继续）…".format(
            "{} 秒".format(self.timeout) if self.timeout else "不限"))

        deadline = time.time() + self.timeout if self.timeout else None
        while deadline is None or time.time() < deadline:
            data = self._read_json(A_PATH)
            if data and (data.get("id") == qid or data.get("skip")):
                answers = data.get("answers") or {}
                rows = []
                for i, q in enumerate(qs):
                    a = str(answers.get(str(i)) or "").strip()
                    if data.get("skip"):
                        rows.append((q["q"], q.get("suggest") or "（无）", SRC_SKIP))
                    elif a:
                        rows.append((q["q"], a, SRC_USER))
                    else:
                        rows.append((q["q"], q.get("suggest") or "（无）", SRC_SUGGEST))
                self._cleanup()
                for q, a, src in rows:
                    print("  已回答：{} -> {}（{}）".format(q, a, src))
                return rows
            time.sleep(POLL_SEC)
        self._cleanup()
        rows = [(q["q"], q.get("suggest") or "（无）", SRC_TIMEOUT) for q in qs]
        for q, a, _src in rows:
            print("  超时未答，按建议继续：{} -> {}".format(q, a))
        return rows

    def _ask_stdin(self, title, qs):
        self._print_qs(title, qs)
        rows = []
        for i, q in enumerate(qs, 1):
            for j, o in enumerate(q.get("options") or [], 1):
                print("    {}. {}".format(j, o))
            try:
                a = input("  问题 {}/{} 你的回答（直接回车用建议「{}」）> ".format(
                    i, len(qs), q.get("suggest") or "无")).strip()
            except (EOFError, KeyboardInterrupt):
                a = ""
            if a:
                rows.append((q["q"], a, SRC_USER))
            else:
                rows.append((q["q"], q.get("suggest") or "（无）", SRC_SUGGEST))
        return rows

    @staticmethod
    def _print_qs(title, qs):
        print("  想请你确认（{}）：".format(title))
        for i, q in enumerate(qs, 1):
            opts = "（{}）".format(" / ".join(q.get("options") or [])) \
                if q.get("options") else ""
            print("  问题 {}：{}{}".format(i, q["q"], opts))

    @staticmethod
    def _read_json(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _cleanup():
        for p in (Q_PATH, A_PATH):
            try:
                os.remove(p)
            except OSError:
                pass

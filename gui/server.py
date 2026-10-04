"""GUI 后端：Flask 只做两件事——托管单页界面，以及用子进程跑各阶段并流式回传日志。

阶段不在 Flask 进程内执行（爬取要长跑、LLM 要重试），而是 spawn
`python -u main.py <阶段>`，stdout 逐行捕获进内存环形缓冲，前端轮询。
"""
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from string import Template

import yaml
from dotenv import dotenv_values
from flask import (Flask, abort, jsonify, request, send_file,
                   send_from_directory)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import safe_join

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from spider import storage  # noqa: E402
from spider.models import ARTICLE_TYPES, CP_COMBOS, ENDINGS  # noqa: E402
from gui import config_schema  # noqa: E402
from pipeline import lore  # noqa: E402

GUI_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(GUI_DIR, "dist")   # Vue 构建产物目录
CONFIG_PATH = os.path.join(ROOT, "config.yaml")
ENV_PATH = os.path.join(ROOT, ".env")

app = Flask(__name__, static_folder=None)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # 本地开发工具：静态资源禁缓存，重建后刷新即生效

SERVER_VERSION = "20261005.16"  # 与 gui/index.html 的 FRONTEND_VERSION 保持一致


@app.errorhandler(HTTPException)
def _json_error(e):
    """所有 abort 统一返回 JSON，前端 toast 直接展示 description。"""
    return jsonify({"error": e.description}), e.code


CONFIG_HEADER = (
    "# 本文件由 GUI 生成/更新（注释会精简，高级配置可直接手改后重启 GUI）\n"
)

STAGES = {
    "crawl": ["crawl"],
    "filter": ["filter"],
    "distill": ["distill"],
    "write": ["write"],
    "runall": ["run-all"],
    "selftest": ["selftest"],
    "chars": ["distill-characters"],
}

STAGE_NAMES = {
    "crawl": "爬取", "filter": "过滤", "distill": "蒸馏",
    "write": "写作", "runall": "一键素材", "selftest": "自测",
    "chars": "蒸馏角色卡",
}

ENV_FIELDS = {
    "LOFTER_COOKIE": {"secret": True},
    "LOFTER_LOGIN_KEY": {"secret": False},
    "LOFTER_LOGIN_AUTH": {"secret": True},
    "LLM_BASE_URL": {"secret": False},
    "LLM_API_KEY": {"secret": True},
    "LLM_MODEL": {"secret": False},
}

# 可写配置白名单：由 config_schema 派生，加配置项只改 schema 一处
ALLOWED_CONFIG = config_schema.allowed_config()

# ----------------------------------------------------------------------
# 日志与进程状态
_log_lock = threading.Lock()
_logs = deque(maxlen=8000)
_log_seq = 0
_proc_lock = threading.Lock()
_proc = {"proc": None, "stage": None, "exit_code": None, "started_at": None,
         "last_result": None}


GUI_LOG_PATH = os.path.join(storage.DATA_DIR, "gui_log.txt")


def _append_log(text):
    global _log_seq
    with _log_lock:
        _logs.append({"i": _log_seq, "t": time.strftime("%H:%M:%S"), "text": text})
        _log_seq += 1
        try:   # 持久化：重开窗口也能看到最近日志
            os.makedirs(storage.DATA_DIR, exist_ok=True)
            with open(GUI_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), text))
            if os.path.getsize(GUI_LOG_PATH) > 2_000_000:   # 超 2MB 只留最后 1000 行
                with open(GUI_LOG_PATH, encoding="utf-8", errors="replace") as f:
                    tail = f.readlines()[-1000:]
                with open(GUI_LOG_PATH, "w", encoding="utf-8") as f:
                    f.writelines(tail)
        except OSError:
            pass


def _load_recent_logs(limit=300):
    """启动时把最近日志载入内存，便于重开窗口后回看。"""
    global _log_seq
    if not os.path.exists(GUI_LOG_PATH):
        return
    try:
        with open(GUI_LOG_PATH, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-limit:]
    except OSError:
        return
    with _log_lock:
        for line in tail:
            line = line.rstrip("\n")
            m = re.match(r"^\[(\d{2}:\d{2}:\d{2})\] (.*)$", line)
            if not m:
                continue
            _logs.append({"i": _log_seq, "t": m.group(1), "text": m.group(2)})
            _log_seq += 1


_load_recent_logs()


def _reader_thread(proc, stage):
    last_err = ""
    for line in proc.stdout:
        text = line.rstrip("\n")
        if re.search(r"(失败|错误|Traceback|Error|SystemExit|异常|不存在|请先)", text):
            last_err = text.strip()
        _append_log(text)
    code = proc.wait()
    with _proc_lock:
        _proc["exit_code"] = code
        _proc["proc"] = None
        # 结构化的阶段结果：前端据此显示红色失败态，而不是只有一行 exit code 滚进日志
        _proc["last_result"] = {
            "stage": stage,
            "ok": code == 0,
            "exit_code": code,
            "finished_at": int(time.time()),
            "error_summary": ("" if code == 0 else (last_err[-300:] or "进程异常退出")),
        }
    suffix = "" if code == 0 else f"（退出码 {code}，看上方日志找原因）"
    _append_log(f"—— {STAGE_NAMES.get(stage, stage)} 结束{suffix} ——")


def _spawn(stage, idea=None, extra=None):
    argv = [sys.executable, "-u", "main.py"] + list(STAGES[stage])
    if stage == "write":
        argv += ["-i", idea] + list(extra or [])
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
           "DISTILLER_ASK_GUI": "1"}   # 写作提问走 data/ask/ 文件问答（见 pipeline/ask_user.py）
    proc = subprocess.Popen(
        argv, cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    with _proc_lock:
        _proc["proc"] = proc
        _proc["stage"] = stage
        _proc["exit_code"] = None
        _proc["started_at"] = time.time()
    threading.Thread(target=_reader_thread, args=(proc, stage), daemon=True).start()


def running_stage():
    with _proc_lock:
        return _proc["stage"] if _proc["proc"] else None


# ----------------------------------------------------------------------
# 配置读写
def load_config():
    config_schema.write_defaults_if_missing(CONFIG_PATH)   # 新克隆/新机器：自动生成默认配置
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _coerce(value, typ):
    if value is None:
        return None
    if typ is str:
        return str(value)
    if typ is int:
        return int(float(value))
    if typ is float:
        return float(value)
    if typ is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)
    if typ is list:
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return [s.strip() for s in str(value).replace("，", ",").split("\n") if s.strip()]
    if typ == "agentlist":   # 团队成员：list of dict
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if not isinstance(item, dict):
                continue
            out.append({"name": str(item.get("name", "")).strip()[:30] or "成员",
                        "model": str(item.get("model", "")).strip(),
                        "thinking": str(item.get("thinking", "")).strip(),
                        "perspective": str(item.get("perspective", "")).strip()})
        return [a for a in out if a["perspective"] or a["name"]]
    if typ == "providerlist":   # 模型提供商：list of dict（兼容手写的 dict 形态）
        if isinstance(value, dict):   # 手写 yaml 常见 {名字: {base_url, api_key}}
            value = [dict(v, name=k) for k, v in value.items() if isinstance(v, dict)]
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()[:30]
            if not name:
                continue
            api_key = str(item.get("api_key", "")).strip()
            if "****" in api_key:   # 界面回传的是脱敏值：保留已保存的真 key
                api_key = _existing_provider_key(name)
            out.append({"name": name,
                        "base_url": str(item.get("base_url", "")).strip(),
                        "api_key": api_key})
        return out
    return value


def _set_path(d, dotted, value):
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _load_config_rt():
    """读 config.yaml 并保留注释结构，供保存时原样写回。

    优先 ruamel.yaml（保住用户手写注释）；没有就退化为 PyYAML（注释会丢，
    这时至少把 schema 里的字段说明写进文件头）。
    """
    try:
        from ruamel.yaml import YAML
    except ImportError:
        return None, load_config()
    y = YAML()
    y.preserve_quotes = True
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return y, (y.load(f) or {})
    except Exception:  # noqa: BLE001 文件损坏时兜底
        return y, load_config()


def _existing_provider_key(name):
    """从当前 config.yaml 里取某提供商已保存的 api_key（脱敏值回传时不覆盖真值）。"""
    try:
        providers = load_config().get("providers") or []
    except Exception:  # noqa: BLE001 配置文件暂时读不了就当没有
        return ""
    if isinstance(providers, list):
        for item in providers:
            if isinstance(item, dict) and (item.get("name") or "").strip() == name:
                return str(item.get("api_key") or "").strip()
    return ""


def _masked_config(cfg):
    """返回 providers[].api_key 脱敏后的配置副本（不把真 key 回传给前端）。"""
    cfg = json.loads(json.dumps(cfg or {}))
    for p in (cfg.get("providers") or []):
        if isinstance(p, dict):
            key = str(p.get("api_key") or "")
            if key:
                p["api_key"] = (key[:4] + "****") if len(key) > 8 else "****"
    return cfg


def update_config(patch):
    y, cfg = _load_config_rt()
    if not isinstance(cfg, dict):
        cfg = {}
    changed = []
    for dotted, value in patch.items():
        if dotted not in ALLOWED_CONFIG:
            abort(400, f"不支持的配置项：{dotted}")
        try:
            coerced = _coerce(value, ALLOWED_CONFIG[dotted])
        except (TypeError, ValueError):
            abort(400, f"{dotted} 的值不合法：{value!r}")
        _set_path(cfg, dotted, coerced)
        changed.append(dotted)
    if y is not None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            y.dump(cfg, f)
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(CONFIG_HEADER)
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return changed


def env_status():
    vals = dotenv_values(ENV_PATH) if os.path.exists(ENV_PATH) else {}
    out = {}
    for key, meta in ENV_FIELDS.items():
        v = vals.get(key) or ""
        if meta["secret"]:
            hint = (v[:4] + "…" + v[-4:]) if len(v) > 10 else ("已填写" if v else "")
            out[key] = {"set": bool(v), "hint": hint, "value": None}
        else:
            out[key] = {"set": bool(v), "hint": "", "value": v}
    return out


def update_env(updates):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, encoding="utf-8") as f:
            lines = f.read().splitlines()
    changed = []
    for key, value in (updates or {}).items():
        if key not in ENV_FIELDS:
            abort(400, f"不支持的 .env 项：{key}")
        value = (value or "").strip()
        if value == "":
            continue  # 留空 = 保持不变
        pattern = re.compile(r"^" + re.escape(key) + r"=.*$")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
        changed.append(key)
    if changed:
        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return changed


# ----------------------------------------------------------------------
def _stats():
    def n(path):
        return len(storage.load_jsonl(path, dict_only=True)) if os.path.exists(path) else 0
    # 知识库按分类子目录列出，相对路径形如「CP向·男男/桥段与爽点.md」
    knowledge = []
    if os.path.isdir(storage.KNOWLEDGE_DIR):
        for d in sorted(os.listdir(storage.KNOWLEDGE_DIR)):
            p = os.path.join(storage.KNOWLEDGE_DIR, d)
            if os.path.isdir(p):
                knowledge.extend(f"{d}/{f}" for f in sorted(os.listdir(p)) if f.endswith(".md"))
            elif d.endswith(".md"):
                knowledge.append(d)  # 兼容旧的扁平结构
    outputs = sorted((f for f in os.listdir(storage.OUTPUT_DIR) if f.endswith(".md")),
                     reverse=True) if os.path.isdir(storage.OUTPUT_DIR) else []
    # 成果分组：正文 / 讨论记录 / 提示词——混在一起会被当成"生成的文章"
    def _kind(fn):
        if "提示词" in fn:
            return "prompt"
        if "讨论记录" in fn:
            return "discussion"
        return "article"
    output_groups = {"article": [], "discussion": [], "prompt": []}
    for f in outputs:
        output_groups[_kind(f)].append(f)
    type_counter = {}
    for d in (storage.load_jsonl(storage.FILTERED_JSONL, dict_only=True)
              if os.path.exists(storage.FILTERED_JSONL) else []):
        t = d.get("article_type")
        if t:
            type_counter[t] = type_counter.get(t, 0) + 1
    return {
        "posts": n(storage.POSTS_JSONL),
        "filtered": n(storage.FILTERED_JSONL),
        "excluded": n(storage.EXCLUDED_JSONL),
        "distilled": n(storage.DISTILLED_JSONL),
        "knowledge": knowledge,
        "outputs": outputs,
        "output_groups": output_groups,
        "types": type_counter,
        "charcards": len(storage.distilled_card_files()),
    }


def _build_id():
    """dist/index.html 的指纹：文件一变即新值，前端据此自动刷新。"""
    try:
        st = os.stat(os.path.join(DIST_DIR, "index.html"))
        return "{}-{}".format(int(st.st_mtime), st.st_size)
    except OSError:
        return "none"


@app.get("/")

def index():
    index_html = os.path.join(DIST_DIR, "index.html")
    if os.path.isfile(index_html):
        return send_from_directory(DIST_DIR, "index.html")
    return ("<!doctype html><meta charset='utf-8'><body style='font-family:sans-serif;"
            "padding:40px;line-height:2'>前端尚未构建。<br>"
            "请在项目目录执行：<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>"
            "</body>", 200)


@app.get("/assets/<path:fname>")
def assets(fname):
    return send_from_directory(os.path.join(DIST_DIR, "assets"), fname)


@app.get("/api/post-content")
def api_post_content():
    """按 url 在 filtered/posts/excluded 里找文章全文，供阅读器展示。"""
    url = (request.args.get("url") or "").strip()
    if not url:
        abort(400, "缺少 url 参数")
    for path in (storage.FILTERED_JSONL, storage.POSTS_JSONL, storage.EXCLUDED_JSONL):
        if not os.path.exists(path):
            continue
        for d in storage.load_jsonl(path, dict_only=True):
            if d.get("url") == url:
                content = (d.get("long_text") or d.get("content_md") or "").strip()
                return jsonify({
                    "title": d.get("title") or "（无标题）",
                    "author": d.get("author") or "",
                    "publish_time": d.get("publish_time") or "",
                    "tags": d.get("tags") or [],
                    "url": url,
                    "content": content or "（该文章没有可读的正文，可能是图片帖。）",
                })
    abort(404, "未找到该文章，可能已被清理")


def _persona_path(name):
    """人设文件安全路径：只允许 .md/.txt、禁止穿越。"""
    if not name.lower().endswith((".md", ".txt")):
        abort(400, "人设文件只支持 .md/.txt")
    joined = safe_join(storage.PERSONAS_DIR, name)
    if not joined:
        abort(404)
    return joined


@app.get("/api/character-cards")
def api_charcards_list():
    return jsonify({"files": [{"file": fn, "name": os.path.splitext(fn)[0]}
                              for fn in storage.distilled_card_files()]})


@app.get("/api/character-cards/<name>")
def api_charcard_get(name):
    safe = storage._safe_name(name) + ".md"
    path = os.path.join(storage.PERSONAS_DISTILLED_DIR, safe)
    if not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        return jsonify({"name": safe[:-3], "content": f.read()})


@app.get("/api/personas")
def api_personas_list():
    files = []
    all_p = storage.parse_personas()
    for fn in storage.persona_files():
        names = [p["name"] for p in all_p if p["file"] == fn]
        files.append({"file": fn, "names": names,
                      "chars": os.path.getsize(os.path.join(storage.PERSONAS_DIR, fn))})
    return jsonify({"files": files})


@app.post("/api/personas")
def api_personas_upload():
    files = request.files.getlist("files")
    if not files:
        abort(400, "没有收到文件")
    os.makedirs(storage.PERSONAS_DIR, exist_ok=True)
    saved = []
    for f in files:
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", os.path.basename(f.filename or "")).strip()
        if not name:
            continue
        if not name.lower().endswith((".md", ".txt")):
            name += ".md"
        f.save(os.path.join(storage.PERSONAS_DIR, name))
        saved.append(name)
    if not saved:
        abort(400, "没有有效的 .md/.txt 文件")
    return jsonify({"ok": True, "saved": saved})


@app.get("/api/personas/<name>")
def api_persona_get(name):
    path = _persona_path(name)
    if not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        return jsonify({"name": name, "content": f.read()})


@app.delete("/api/personas/<name>")
def api_persona_delete(name):
    path = _persona_path(name)
    if not os.path.isfile(path):
        abort(404)
    os.remove(path)
    return jsonify({"ok": True})


# ======================================================================
# 设定/剧情素材库（data/lore/）：写作查询工具的资料来源
# ======================================================================
@app.get("/api/lore")
def api_lore_list():
    files = []
    for f in lore.lore_files():
        path = lore._safe_join(f["rel"])
        try:
            mtime = int(os.path.getmtime(path)) if path and os.path.exists(path) else 0
        except OSError:
            mtime = 0
        files.append({**f, "mtime": mtime})
    return jsonify({"files": files})


@app.post("/api/lore")
def api_lore_upload():
    files = request.files.getlist("files")
    if not files:
        abort(400, "没有收到文件")
    saved = []
    for f in files:
        name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", os.path.basename(f.filename or "")).strip()
        if not name:
            continue
        if not name.lower().endswith((".md", ".txt")):
            name += ".md"
        lore.lore_write(name, f.read().decode("utf-8", errors="replace"))
        saved.append(name)
    if not saved:
        abort(400, "没有有效的 .md/.txt 文件")
    return jsonify({"ok": True, "saved": saved})


@app.get("/api/lore/<path:rel>")
def api_lore_get(rel):
    text = lore.lore_read(rel)
    if text is None:
        abort(404)
    return jsonify({"rel": rel, "content": text})


@app.delete("/api/lore/<path:rel>")
def api_lore_delete(rel):
    if not lore.lore_delete(rel):
        abort(404)
    return jsonify({"ok": True})


@app.get("/api/state")
def api_state():
    return jsonify({
        "server_version": SERVER_VERSION,
        "config": _masked_config(load_config()),
        "env": env_status(),
        "stats": _stats(),
        "running": running_stage(),
    })


@app.get("/api/config-schema")
def api_config_schema():
    """配置项元数据：前端据此自动生成表单，加配置项只改 schema 一处。"""
    return jsonify(config_schema.fields_json())


@app.get("/api/data")
def api_data():
    return jsonify(_stats())


@app.post("/api/config")
def api_config():
    changed = update_config(request.get_json(force=True))
    return jsonify({"ok": True, "changed": changed})


@app.post("/api/env")
def api_env():
    changed = update_env(request.get_json(force=True))
    return jsonify({"ok": True, "changed": changed})


@app.get("/api/logs")
def api_logs():
    since = request.args.get("since", 0, type=int)
    with _log_lock:
        lines = [e for e in _logs if e["i"] > since]
        last = _logs[-1]["i"] if _logs else since
    with _proc_lock:
        running = _proc["stage"] if _proc["proc"] else None
        elapsed = int(time.time() - _proc["started_at"]) if (
            running and _proc["started_at"]) else None
        return jsonify({
            "lines": lines, "last": last,
            "running": running,
            "elapsed": elapsed,
            "exit_code": _proc["exit_code"],
            "stage_result": _proc["last_result"],
            "question": _current_question(),
            "build": _build_id(),
        })


# ======================================================================
# 写作提问：pipeline/ask_user.py 落盘问题，界面回答后写回答案文件
ASK_DIR = os.path.join(storage.DATA_DIR, "ask")
ASK_Q_PATH = os.path.join(ASK_DIR, "question.json")
ASK_A_PATH = os.path.join(ASK_DIR, "answer.json")


def _current_question():
    """当前待答问题；文件缺失/损坏/已过期返回 None（过期的顺手清掉）。"""
    try:
        with open(ASK_Q_PATH, encoding="utf-8") as f:
            q = json.load(f)
    except (OSError, ValueError):
        return None
    exp = q.get("expires_at")
    if exp and time.time() > exp:
        try:
            os.remove(ASK_Q_PATH)
        except OSError:
            pass
        return None
    return q


@app.post("/api/answer")
def api_answer():
    """回答当前问题：写 data/ask/answer.json，写作进程下一轮轮询即继续。"""
    body = request.get_json(force=True) or {}
    q = _current_question()
    if not q:
        abort(409, "没有待回答的问题（可能已超时，写作已按建议继续）")
    if str(body.get("id") or "") != str(q.get("id") or ""):
        abort(409, "问题已更新，请刷新后再答")
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        abort(400, "answers 格式不对")
    os.makedirs(ASK_DIR, exist_ok=True)
    with open(ASK_A_PATH, "w", encoding="utf-8") as f:
        json.dump({"id": q.get("id"), "skip": bool(body.get("skip")),
                   "answers": {str(k): str(v) for k, v in answers.items()}},
                  f, ensure_ascii=False)
    try:
        os.remove(ASK_Q_PATH)      # 先清问题，界面立刻收起提问面板
    except OSError:
        pass
    return jsonify({"ok": True})


@app.post("/api/run")
def api_run():
    body = request.get_json(force=True)
    stage = body.get("stage")
    if stage not in STAGES:
        abort(400, f"未知阶段：{stage}")
    if running_stage():
        abort(409, "已有阶段在运行，请先停止或等待结束")
    idea = (body.get("idea") or "").strip()
    extra = []
    if stage == "write":
        from pipeline.writer import MODES, RATINGS
        mode = (body.get("mode") or "auto").strip()
        if mode not in MODES:
            abort(400, f"未知写作方式：{mode}")
        t = (body.get("article_type") or "").strip()
        c = (body.get("cp_combo") or "").strip()
        e = (body.get("ending") or "").strip()
        rt = (body.get("rating") or "").strip()
        if t and t not in ARTICLE_TYPES:
            abort(400, f"未知文章类型：{t}")
        if c and c not in CP_COMBOS:
            abort(400, f"未知CP组合：{c}")
        if e and e not in ENDINGS and e != "不限":
            abort(400, f"未知结局类型：{e}")
        if t == "单人向":
            c = "微量"  # 单人向强制微量
        extra = [f"--mode={mode}"]
        ps = (body.get("persona_source") or "").strip()
        ow = body.get("official_weight")
        if ps:
            if ps not in ("both", "distilled", "official"):
                abort(400, f"未知人物卡来源：{ps}")
            extra.append(f"--persona-source={ps}")
        if ow is not None and str(ow) != "":
            try:
                w = max(0, min(100, int(ow)))
            except ValueError:
                abort(400, "official_weight 必须是 0~100 的整数")
            extra.append(f"--official-weight={w}")
        # 空参数不传，让 CLI 落回 config 默认值（argparse 的 choices 不收空串）
        if t:
            extra.append(f"--type={t}")
        if c:
            extra.append(f"--cp={c}")
        if e:
            extra.append(f"--ending={e}")
        if rt:
            if rt not in RATINGS:
                abort(400, f"未知内容分级：{rt}")
            extra.append(f"--rating={rt}")
        if mode in ("auto", "quick"):
            if not idea:
                abort(400, "写作前先写下你的想法")
            if mode == "quick" and body.get("roster_all"):
                extra.append("--all-roster")
        else:
            draft = body.get("draft") or ""
            if len(draft) > 200_000:
                abort(400, "原稿太长（上限 20 万字符），请拆分后分次处理")
            if not draft.strip():
                abort(400, "「{}」方式需要先粘贴你的原稿".format(MODES[mode]))
            os.makedirs(storage.DATA_DIR, exist_ok=True)
            draft_path = os.path.join(storage.DATA_DIR, "draft.tmp")
            with open(draft_path, "w", encoding="utf-8") as f:
                f.write(draft)
            extra += ["--file", draft_path]
    if stage == "crawl" and not (load_config().get("crawl", {}).get("tag") or "").strip():
        abort(400, "先到「配置」页填 tag 名")
    _append_log(f"—— 开始{STAGE_NAMES[stage]}" + ("——" if stage != "write" else f"：{idea or '（见原稿）'} ——"))
    _spawn(stage, idea, extra)
    return jsonify({"ok": True, "stage": stage})


@app.post("/api/stop")
def api_stop():
    with _proc_lock:
        proc = _proc["proc"]
        stage = _proc["stage"]
    if not proc:
        abort(409, "当前没有在运行的阶段")
    proc.terminate()
    _append_log("—— 已发送停止信号，等待进程退出 ——")
    return jsonify({"ok": True, "stage": stage})


@app.get("/api/posts")
def api_posts():
    kind = request.args.get("kind", "posts")
    path = {"posts": storage.POSTS_JSONL, "filtered": storage.FILTERED_JSONL,
            "excluded": storage.EXCLUDED_JSONL}.get(kind)
    if not path:
        abort(400, f"未知数据类型：{kind}")
    items = storage.load_jsonl(path, dict_only=True) if os.path.exists(path) else []
    # 筛选/搜索：让界面上能回答"它给我分了什么类、为什么被排除"
    q = (request.args.get("q") or "").strip().lower()
    f_type = (request.args.get("article_type") or "").strip()
    f_cp = (request.args.get("cp_combo") or "").strip()
    f_ending = (request.args.get("ending") or "").strip()

    def _keep(d):
        if f_type and (d.get("article_type") or "") != f_type:
            return False
        if f_cp and (d.get("cp_combo") or "") != f_cp:
            return False
        if f_ending and (d.get("ending") or "") != f_ending:
            return False
        if q:
            hay = " ".join([d.get("title") or "", d.get("author") or "",
                            " ".join(d.get("tags") or [])]).lower()
            if q not in hay:
                return False
        return True

    items = [d for d in items if _keep(d)]
    total = len(items)
    # 列排序：界面上点表头切换。显式排序后按该键排，否则维持原有「页内倒序」展示
    sort = (request.args.get("sort") or "").strip()
    order = (request.args.get("order") or "").strip().lower()
    if sort in ("hot", "publish_time", "title"):
        def _key(d):
            v = d.get(sort)
            if sort == "hot":
                return v or 0
            return (v or "").lower() if isinstance(v, str) else (v or "")
        items.sort(key=_key, reverse=(order != "asc"))
    page = max(1, request.args.get("page", 1, type=int))
    size = min(100, max(10, request.args.get("size", 30, type=int)))
    start = (page - 1) * size
    rows = []
    page_items = items[start:start + size]
    if not sort:
        page_items = page_items[::-1]
    for d in page_items:
        a_type = d.get("article_type") or ""
        cp = d.get("cp_combo") or ""
        rows.append({
            "title": d.get("title") or "（无标题）",
            "author": d.get("author") or "",
            "post_type": d.get("post_type") or "",
            "publish_time": d.get("publish_time") or "",
            "hot": d.get("hot") or 0,
            "url": d.get("url") or "",
            "tags": d.get("tags") or [],
            "reason": d.get("exclude_reason") or "",
            "article_type": a_type,
            "cp_combo": cp,
            "ending": d.get("ending") or "",
            "category": f"{a_type}·{cp}" if a_type and cp else a_type or cp or "",
            "confidence": d.get("confidence"),
        })
    return jsonify({"total": total, "page": page, "size": size, "items": rows})


@app.get("/api/file/<kind>/<path:name>")
def api_file(kind, name):
    """name 可含子目录（知识库按分类存放），safe_join 防目录穿越。"""
    base = {"knowledge": storage.KNOWLEDGE_DIR, "output": storage.OUTPUT_DIR}.get(kind)
    if not base:
        abort(404)
    joined = safe_join(base, name)
    if not joined or not os.path.isfile(joined):
        abort(404)
    with open(joined, encoding="utf-8") as f:
        return jsonify({"name": name, "content": f.read()})


# ======================================================================
# 提示词：在线编辑 + 自动备份回滚
# ======================================================================
PROMPTS_DIR = os.path.join(ROOT, "prompts")
PROMPTS_BACKUP_DIR = os.path.join(storage.DATA_DIR, "prompts_backup")


def _template_vars(text):
    """取出模板里的 $变量名，用来防改坏占位符（load_prompt 用 substitute，缺一个就 KeyError）。"""
    try:
        return sorted(Template(text or "").get_identifiers())   # Python 3.11+
    except AttributeError:
        pat = re.compile(r"\$(?:\$)|\$([_a-z][_a-z0-9]*)", re.I)
        return sorted({m.group(1) for m in pat.finditer(text or "") if m.group(1)})


def _prompt_path(name):
    if not name.endswith(".md") or any(s in name for s in ("/", "\\", "..")):
        abort(400, "提示词名不合法")
    joined = safe_join(PROMPTS_DIR, name)
    if not joined:
        abort(404)
    return joined


@app.get("/api/prompts")
def api_prompts():
    items = []
    for fn in sorted(os.listdir(PROMPTS_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(PROMPTS_DIR, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        items.append({"name": fn, "vars": _template_vars(text), "chars": len(text),
                      "mtime": int(os.path.getmtime(path))})
    return jsonify({"items": items})


@app.get("/api/prompts/<name>")
def api_prompt_get(name):
    path = _prompt_path(name)
    if not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    backups = []
    if os.path.isdir(PROMPTS_BACKUP_DIR):
        stem = os.path.splitext(name)[0]
        for fn in sorted(os.listdir(PROMPTS_BACKUP_DIR), reverse=True):
            if fn.startswith(stem + ".") and fn.endswith(".md"):
                backups.append(fn)
    return jsonify({"name": name, "content": text, "vars": _template_vars(text),
                    "backups": backups[:20]})


@app.put("/api/prompts/<name>")
def api_prompt_put(name):
    path = _prompt_path(name)
    body = request.get_json(force=True) or {}
    content = str(body.get("content") or "")
    if not content.strip():
        abort(400, "内容不能为空")
    required = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            required = _template_vars(f.read())
    missing = [v for v in required if v not in _template_vars(content)]
    if missing:
        abort(400, "占位符被删掉了：{} —— 这些 $变量必须保留，否则运行时会报错".format(
            "、".join("$" + v for v in missing)))
    os.makedirs(PROMPTS_BACKUP_DIR, exist_ok=True)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
        bak = os.path.join(PROMPTS_BACKUP_DIR, "{}.{}.md".format(
            os.path.splitext(name)[0], time.strftime("%Y%m%d-%H%M%S")))
        with open(bak, "w", encoding="utf-8") as f:
            f.write(old)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "vars": _template_vars(content)})


@app.post("/api/prompts/<name>/restore")
def api_prompt_restore(name):
    path = _prompt_path(name)
    body = request.get_json(force=True) or {}
    bak_name = str(body.get("backup") or "")
    if any(s in bak_name for s in ("/", "\\", "..")):
        abort(400, "备份名不合法")
    bak = safe_join(PROMPTS_BACKUP_DIR, bak_name) if bak_name else None
    if not bak or not os.path.isfile(bak):
        abort(404, "备份不存在")
    with open(bak, encoding="utf-8") as f:
        content = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return jsonify({"ok": True, "name": name, "content": content,
                    "vars": _template_vars(content)})


# ======================================================================
# 连通性验证：让小白在跑长任务之前就知道登录/模型有没有配对
# ======================================================================
def _cookie_kwargs():
    vals = dotenv_values(ENV_PATH) if os.path.exists(ENV_PATH) else {}
    return {"cookie": (vals.get("LOFTER_COOKIE") or "").strip() or None,
            "login_key": (vals.get("LOFTER_LOGIN_KEY") or "").strip() or None,
            "login_auth": (vals.get("LOFTER_LOGIN_AUTH") or "").strip() or None}


@app.post("/api/verify/llm")
def api_verify_llm():
    """一次极小的真实调用，验证模型端点可用。

    body 可带 {"model": "提供商名/模型名 或 纯模型名"}：测指定模型
    （含 providers 里的其他提供商）；不带则测 .env 主模型。
    """
    body = request.get_json(silent=True) or {}
    model_ref = str(body.get("model") or "").strip()
    try:
        from dotenv import load_dotenv
        # .env 可能刚在界面上改过：进程启动时只读过一次，这里强制重载
        load_dotenv(ENV_PATH, override=True)
        from llm.client import LLMClient, llm_for
        client = llm_for(model_ref, LLMClient(), load_config().get("providers"))
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "model": model_ref, "note": "模型配置不完整：" + str(e)[:200]})
    try:
        out = client.chat(system="你是连通性探针。", user="只回复两个字：正常",
                          temperature=0, retries=1, timeout=30)
        return jsonify({"ok": True, "model": client.label,
                        "note": "已连通，模型回复：" + (out or "").strip()[:40]})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "model": client.label,
                        "note": "调用失败：" + str(e)[:200]})


@app.post("/api/verify/lofter")
def api_verify_lofter():
    """粗检登录态：未登录时访问主页会被带去登录页。"""
    kw = _cookie_kwargs()
    if not kw["cookie"] and not (kw["login_key"] and kw["login_auth"]):
        return jsonify({"ok": False, "note": "还没有配置 Lofter Cookie，先到「设置 · 基础」填。"})
    try:
        from spider.dwr_client import DwRClient
        ok, url = DwRClient(**kw).check_login()
        return jsonify({"ok": bool(ok),
                        "note": "登录有效" if ok else
                        "Cookie 可能已失效（被带去 {}）——重新从浏览器复制一份".format(url)})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "note": "检测失败：" + str(e)[:200]})


# ======================================================================
# 成果文件管理：删除 / 重命名 / 导出
# ======================================================================
def _output_path(name):
    if not name.endswith(".md") or any(s in name for s in ("/", "\\", "..")):
        abort(400, "文件名不合法")
    joined = safe_join(storage.OUTPUT_DIR, name)
    if not joined:
        abort(404)
    return joined


@app.get("/api/output/<name>/export")
def api_output_export(name):
    path = _output_path(name)
    if not os.path.isfile(path):
        abort(404)
    # 先读进内存再回传：Windows 下 send_file 会占住句柄，导致紧接着的删除报「文件被占用」
    with open(path, "rb") as f:
        data = f.read()
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=os.path.basename(path),
                     mimetype="text/markdown; charset=utf-8")


@app.delete("/api/output/<name>")
def api_output_delete(name):
    path = _output_path(name)
    if not os.path.isfile(path):
        abort(404)
    try:
        os.remove(path)
    except PermissionError:
        abort(400, "文件正被占用（可能刚在下载），稍等一下再删")
    return jsonify({"ok": True})


@app.post("/api/output/<name>/rename")
def api_output_rename(name):
    src = _output_path(name)
    if not os.path.isfile(src):
        abort(404)
    body = request.get_json(force=True) or {}
    new_name = str(body.get("to") or "").strip()
    if not new_name.lower().endswith(".md"):
        new_name += ".md"
    dst = _output_path(new_name)
    if os.path.exists(dst):
        abort(400, "已存在同名文件")
    os.rename(src, dst)
    return jsonify({"ok": True, "name": os.path.basename(dst)})

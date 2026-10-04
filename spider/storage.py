"""爬取与管道产物的落盘：jsonl、进度文件、txt 备份。

数据目录默认是项目下的 data/；设置环境变量 DISTILLER_DATA_DIR 可指向
别处——自动化测试必须用这个变量把数据隔离到沙盒目录，绝不碰真实数据。
"""
import json
import os
import re

from spider.models import Post

DATA_DIR = os.environ.get("DISTILLER_DATA_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
POSTS_JSONL = os.path.join(DATA_DIR, "posts", "posts.jsonl")
PROGRESS_JSON = os.path.join(DATA_DIR, "posts", "progress.json")
TXT_DIR = os.path.join(DATA_DIR, "posts", "txt")
FILTERED_JSONL = os.path.join(DATA_DIR, "posts", "filtered.jsonl")
EXCLUDED_JSONL = os.path.join(DATA_DIR, "posts", "excluded.jsonl")
DISTILLED_JSONL = os.path.join(DATA_DIR, "posts", "distilled.jsonl")
KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge")
PERSONAS_DIR = os.path.join(DATA_DIR, "personas")
PERSONAS_DISTILLED_DIR = os.path.join(DATA_DIR, "personas_distilled")   # 蒸馏人物卡（来自同人文）
CHAR_CACHE_JSONL = os.path.join(DATA_DIR, "posts", "character_cache.jsonl")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")

_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


def ensure_dirs():
    for d in (os.path.dirname(POSTS_JSONL), TXT_DIR, KNOWLEDGE_DIR, OUTPUT_DIR,
              PERSONAS_DIR, PERSONAS_DISTILLED_DIR):
        os.makedirs(d, exist_ok=True)


PERSONA_EXTS = (".md", ".txt")


def persona_files():
    if not os.path.isdir(PERSONAS_DIR):
        return []
    return [fn for fn in sorted(os.listdir(PERSONAS_DIR))
            if fn.lower().endswith(PERSONA_EXTS)]


def parse_personas():
    """解析本地人设：data/personas/ 下的 .md/.txt。

    文件里每个一级标题（# 名字）算一个角色，标题下的内容是该角色的人设；
    没有一级标题的文件整体算一个角色（名字取文件名）。
    返回 [{file, name, content}]。
    """
    out = []
    for fn in persona_files():
        path = os.path.join(PERSONAS_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            continue
        if not text:
            continue
        stem = os.path.splitext(fn)[0]
        parts = re.split(r"(?m)^#\s+(.+?)\s*$", text)
        if len(parts) >= 3:  # 有一级标题：成对取出 (名字, 内容)
            for i in range(1, len(parts) - 1, 2):
                name, body = parts[i].strip(), parts[i + 1].strip()
                if body:
                    out.append({"file": fn, "name": name or stem, "content": body})
        else:
            out.append({"file": fn, "name": stem, "content": text})
    return out


def distilled_card_files():
    """蒸馏人物卡目录下的 .md 文件名列表。"""
    if not os.path.isdir(PERSONAS_DISTILLED_DIR):
        return []
    return [fn for fn in sorted(os.listdir(PERSONAS_DISTILLED_DIR))
            if fn.lower().endswith(PERSONA_EXTS)]


def card_is_hollow(text):
    """空壳卡判定：只剩标题/说明/小节名，任何一节都没有条目。

    素材不足的角色会蒸馏出这种卡，注入提示词等于给模型一张白纸，
    因此读卡时直接丢弃（写作端会回落到该角色的官方卡）。
    """
    body = re.sub(r"(?m)^#.*$", "", text or "")        # 标题
    body = re.sub(r"(?m)^>.*$", "", body)              # 说明引用
    body = re.sub(r"(?m)^##.*$", "", body)             # 小节标题
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)  # 注释
    return not body.strip()


def load_distilled_cards():
    """读取全部蒸馏人物卡：[{file, name, content}]（一级标题为角色名）。

    空壳卡（各节无内容）不返回。
    """
    out = []
    for fn in distilled_card_files():
        path = os.path.join(PERSONAS_DISTILLED_DIR, fn)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            continue
        if card_is_hollow(text):
            continue
        if not text:
            continue
        m = re.match(r"(?m)^#\s+(.+?)\s*$", text)
        name = m.group(1).strip() if m else os.path.splitext(fn)[0]
        out.append({"file": fn, "name": name, "content": text})
    return out


def load_char_cache():
    """角色蒸馏缓存：{角色名: {fingerprint, card}}。"""
    path = CHAR_CACHE_JSONL
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                out[obj.get("name")] = obj
            except json.JSONDecodeError:
                continue
    return out


def save_char_cache(cache):
    os.makedirs(os.path.dirname(CHAR_CACHE_JSONL), exist_ok=True)
    with open(CHAR_CACHE_JSONL, "w", encoding="utf-8") as f:
        for obj in cache.values():
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def knowledge_dir(category=None):
    """知识库目录：按「文章类型·CP组合」分子目录，如 knowledge/CP向·男男/。"""
    if not category:
        return KNOWLEDGE_DIR
    safe = _BAD_FILENAME_CHARS.sub("_", category).strip(".") or "未分类"
    return os.path.join(KNOWLEDGE_DIR, safe)


def append_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_jsonl(path, dict_only=False):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if dict_only and not isinstance(obj, dict):
                continue
            out.append(obj)
    return out


def load_posts(path=POSTS_JSONL):
    return [Post.from_dict(d) for d in load_jsonl(path, dict_only=True)]


def load_seen_urls(path=POSTS_JSONL):
    return {d.get("url") for d in load_jsonl(path, dict_only=True) if d.get("url")}


def load_distilled_ids(path=DISTILLED_JSONL):
    return {d.get("post_id") for d in load_jsonl(path, dict_only=True) if d.get("post_id")}


# ----------------------------------------------------------------------
def load_progress():
    if not os.path.exists(PROGRESS_JSON):
        return {}
    try:
        with open(PROGRESS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_progress(state):
    os.makedirs(os.path.dirname(PROGRESS_JSON), exist_ok=True)
    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def reset_progress():
    if os.path.exists(PROGRESS_JSON):
        os.remove(PROGRESS_JSON)


# ----------------------------------------------------------------------
def _safe_name(s, maxlen=80):
    s = _BAD_FILENAME_CHARS.sub(" ", s).strip()
    return (s[:maxlen].strip() or "无标题")


def save_txt_backup(post: Post):
    """按 lofterSpider 的风格存一份 txt，方便直接阅读/核对。"""
    head = ""
    if post.title or post.post_type in ("article", "long"):
        head += f"{post.title} by {post.author}[{post.author_domain}]\n"
    else:
        head += f"{post.author}[{post.author_domain}]\n"
    head += (f"发表时间：{post.publish_time}\n原文链接：{post.url}\n"
             f"tags：{', '.join(post.tags) if post.tags else '无'}\n")

    tail = ""
    if post.images:
        tail += "\n\n文中图片：\n" + "\n".join(post.images)

    content = post.text if post.text else "（无文字内容）"
    body = head + "\n" + content + tail

    name = _safe_name(post.title) if post.title else \
        f"{_safe_name(post.author)}-{post.tags[0] if post.tags else '无tag'}-{post.publish_time[:10]}"
    filename = f"{name} by {_safe_name(post.author)}.txt" if post.title else f"{name}.txt"

    path = os.path.join(TXT_DIR, filename)
    n = 2
    while os.path.exists(path):
        stem, ext = os.path.splitext(filename)
        path = os.path.join(TXT_DIR, f"{stem}({n}){ext}")
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path

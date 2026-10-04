"""设定/剧情素材库（data/lore/）与写作查询工具的检索层。

- data/lore/ 收设定与剧情 .md/.txt（支持子目录），手动放入或 GUI 上传；
- 人物卡沿用 data/personas/（官方/手写）与 data/personas_distilled/（蒸馏）；
- 写作时给模型一份「可查资料索引」，模型在动笔前可输出 JSON 查询（备料），
  这里负责索引构建、查询解析与结果回填（见 writer.py 的章节查询循环）。

data/lore/ 的「lore」取「设定集/世界观资料」之意，与知识库（从同人文蒸馏）互补：
知识库是统计印象，lore 是你认可的硬设定，冲突时以 lore 为准。
"""
import os
import re

from llm.client import extract_json
from spider import storage

LORE_DIR = os.path.join(storage.DATA_DIR, "lore")
LORE_EXTS = (".md", ".txt")


def lore_files():
    """递归扫描 data/lore/ 下的设定/剧情文件，返回 [{rel, name, size}]。

    rel 为相对 data/lore/ 的路径（/ 分隔，展示与查询都用它）。
    """
    out = []
    if not os.path.isdir(LORE_DIR):
        return out
    for root, dirs, files in os.walk(LORE_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for fn in sorted(files):
            if fn.startswith(".") or not fn.lower().endswith(LORE_EXTS):
                continue
            path = os.path.join(root, fn)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            out.append({"rel": os.path.relpath(path, LORE_DIR).replace("\\", "/"),
                        "name": fn, "size": size})
    return out


def _safe_join(rel):
    """把相对路径安全解析到 LORE_DIR 内；为空或越界（../ 等）返回 None。"""
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return None
    base = os.path.normpath(LORE_DIR)
    path = os.path.normpath(os.path.join(base, rel))
    if path != base and not path.startswith(base + os.sep):
        return None
    return path


def lore_read(rel):
    path = _safe_join(rel)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def lore_write(rel, content):
    """写入（GUI 上传/保存）。自动建父目录；越界路径抛 ValueError。"""
    path = _safe_join(rel)
    if not path:
        raise ValueError(f"非法路径：{rel}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def lore_delete(rel):
    path = _safe_join(rel)
    if not path or not os.path.isfile(path):
        return False
    os.remove(path)
    return True


# ----------------------------------------------------------------------
def persona_entries():
    """可查人物卡全集：官方/手写在前、蒸馏在后（同名不重复）。

    返回 [{name, source, content}]；content 不含一级标题。
    """
    entries, seen = [], set()
    for p in storage.parse_personas():
        entries.append({"name": p["name"], "source": "官方", "content": p["content"]})
        seen.add(p["name"])
    for p in storage.load_distilled_cards():
        if p["name"] in seen:
            continue
        entries.append({"name": p["name"], "source": "蒸馏", "content": p["content"]})
        seen.add(p["name"])
    return entries


def resolve_persona(name, entries):
    """按 精确 -> 括号前主干 -> 前缀 -> 子串 找人物卡；找不到返回 None。

    主干匹配兼容「回响(三角洲行动).md」这类文件名与「回响」这种简写。
    """
    q = (name or "").strip()
    if not q:
        return None
    q_low = q.lower()

    def stem(n):
        return re.split(r"[(（]", n)[0].strip().lower()

    for e in entries:
        if e["name"].lower() == q_low:
            return e
    q_stem = stem(q)
    if q_stem:
        for e in entries:
            if stem(e["name"]) == q_stem:
                return e
    for e in entries:
        if e["name"].lower().startswith(q_low):
            return e
    for e in entries:
        if q_low in e["name"].lower():
            return e
    return None


def build_index(entries=None, files=None):
    """给写作提示词的「可查资料索引」；库里什么都没有时返回空串。"""
    entries = persona_entries() if entries is None else entries
    files = lore_files() if files is None else files
    lines = []
    official = [e["name"] for e in entries if e["source"] == "官方"]
    distilled = [e["name"] for e in entries if e["source"] == "蒸馏"]
    if official:
        lines.append("- 官方/手写人物卡：" + "、".join(official))
    if distilled:
        lines.append("- 蒸馏人物卡：" + "、".join(distilled))
    if files:
        lines.append("- 设定/剧情文件：" + "、".join(f["rel"] for f in files))
    return "\n".join(lines)


def tool_instructions(index, rounds):
    """拼进章节提示词的查询工具说明（$lore_tools 变量）。index 为空=不启用。"""
    if not index:
        return ""
    return (
        "可查资料索引（动笔前可按需查阅，不必全部读完）：\n" + index + "\n\n"
        "查询工具：如果本章需要上面某张人物卡的完整内容（预载的可能被截断）、"
        "或某份设定/剧情文件的细节，可以先用一轮查询再动笔——"
        "只输出一个 JSON 对象（不要输出其他文字）：\n"
        '{{"queries": [{{"type": "人物卡", "name": "角色名"}}, '
        '{{"type": "设定", "name": "文件名"}}]}}\n'
        "系统会把查到的内容回传给你再继续；最多可查询 {} 轮。"
        "不需要补充资料、或资料已在提示词里时，直接输出本章正文即可（不要输出 JSON）。"
        .format(max(1, int(rounds)))
    )


def parse_queries(text):
    """判断模型输出是不是备料查询；是则返回查询列表，否则（正文）返回 None。

    约定查询轮只输出 JSON 对象 {"queries": [{"type": "...", "name": "..."}]}。
    """
    try:
        obj = extract_json(text)
    except Exception:  # noqa: BLE001 正文不是 JSON，正常路径
        return None
    if isinstance(obj, dict) and isinstance(obj.get("queries"), list):
        return [q for q in obj["queries"] if isinstance(q, dict)]
    return None


def run_queries(queries, char_limit=4000, entries=None, files=None):
    """执行一批查询，返回回填给模型的文本（每条一个来源块）。"""
    entries = persona_entries() if entries is None else entries
    files = lore_files() if files is None else files
    blocks = []
    for q in (queries or [])[:6]:
        qtype = str(q.get("type") or "").strip()
        name = str(q.get("name") or "").strip()
        if not name:
            continue
        if ("设" in qtype or "剧情" in qtype or "world" in qtype.lower()
                or qtype.lower() in ("lore", "file")):
            text = lore_read(name)
            if text is None:
                avail = "、".join(f["rel"] for f in files) or "（暂无设定文件）"
                blocks.append(f"【设定/{name}】未找到。可用文件：{avail}")
            else:
                blocks.append(f"【设定/{name}】\n{text[:char_limit]}")
        else:
            e = resolve_persona(name, entries)
            if e is None:
                avail = "、".join(x["name"] for x in entries) or "（暂无人物卡）"
                blocks.append(f"【人物卡/{name}】未找到。可用人物：{avail}")
            else:
                content = e["content"]
                if not content.lstrip().startswith("#"):
                    content = f"# {e['name']}\n\n{content}"
                blocks.append("【人物卡/{}（来源：{}）】\n{}".format(
                    e["name"], e["source"], content[:char_limit]))
    return "\n\n".join(blocks)

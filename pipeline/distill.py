"""蒸馏：filtered.jsonl -> 逐篇提炼(map) -> 分批聚合(reduce) -> 知识库 markdown。

- 每篇的提炼结果缓存进 distilled.jsonl（按 post_id 增量，重跑只处理新文章）；
- map 永远提取全部四个维度，config.distill.focus 只决定最终渲染哪些知识库；
- 聚合为两级（分批合并 -> 总合并），避免上千篇时超出上下文。
"""
import json
import os
import time
from collections import Counter
from datetime import datetime

from llm.client import LLMClient, llm_for
from llm.prompts import load_prompt
from spider import storage
from spider.models import category_of

# 单篇喂给 LLM 的正文上限（超长文章截断，蒸馏够用）
ARTICLE_INPUT_LIMIT = 15000

KNOWLEDGE_FILES = {
    "characters": "人设与关系.md",
    "style": "文风.md",
    "tropes": "桥段与爽点.md",
    "warnings": "雷点.md",
}

SCHEMA_EXAMPLE = {
    "characters": [
        {"name": "角色名", "traits": ["性格特征"], "speech": "说话风格/口头禅",
         "dynamics": "与谁的关系及相处模式"}
    ],
    "style": ["这篇的文风特征，如：短句为主、第三人称限知、环境描写烘托情绪"],
    "tropes": [{"name": "桥段名", "detail": "具体怎么写的、为什么戳人"}],
    "highlights": ["值得摘录的金句或名场面（尽量短）"],
    "warnings": ["雷点/败笔/OOC信号，如：某角色被写成工具人"],
}


def _compact(entry):
    """压掉 map 结果里的空字段，减少聚合输入。"""
    out = {}
    for k, v in entry.items():
        if isinstance(v, list) and v:
            out[k] = v
        elif isinstance(v, str) and v:
            out[k] = v
    return out


def run_map(llm, cfg):
    posts = storage.load_posts(storage.FILTERED_JSONL)
    if not posts:
        raise SystemExit("filtered.jsonl 里没有数据，请先运行 python main.py filter")
    min_chars = int(cfg.get("min_text_chars", 100))
    done_ids = storage.load_distilled_ids()
    todo = [p for p in posts
            if p.post_id not in done_ids and len(p.text.strip()) >= min_chars]
    print("待蒸馏 {} 篇（已蒸馏过 {} 篇，因过短跳过 {} 篇）"
          .format(len(todo), len(done_ids), len(posts) - len(todo) - len(done_ids)))

    consec_fail = 0
    for i, post in enumerate(todo, 1):
        user = load_prompt(
            "distill_map",
            schema=json.dumps(SCHEMA_EXAMPLE, ensure_ascii=False, indent=1),
            article=(f"标题：{post.title or '（无）'}\n"
                     f"作者：{post.author}\n"
                     f"tags：{', '.join(post.tags) if post.tags else '无'}\n"
                     f"发表时间：{post.publish_time}\n"
                     f"正文：\n{post.text[:ARTICLE_INPUT_LIMIT]}"),
        )
        t0 = time.time()
        try:
            result = llm.chat_json(
                system="你是同人文学分析师。只输出 JSON，不要输出其他内容。",
                user=user, temperature=0.3,
                timeout=120, retries=2,
            )
        except Exception as e:  # noqa: BLE001 单篇失败不阻塞整体，连续失败要熔断
            consec_fail += 1
            if consec_fail >= 3:
                raise SystemExit(
                    f"LLM 连续 {consec_fail} 篇蒸馏失败，已熔断（最后错误：{e}）。\n"
                    "请检查 LLM 配置和网络后重跑——已蒸馏的都有缓存（distilled.jsonl），"
                    "重跑只处理剩余的。")
            print("  [{}/{}] 蒸馏失败，跳过 {}: {}".format(i, len(todo), post.url, str(e)[:120]))
            continue
        consec_fail = 0
        result = {**result, "post_id": post.post_id, "url": post.url,
                  "title": post.title, "author": post.author,
                  "publish_time": post.publish_time,
                  "article_type": post.article_type,
                  "cp_combo": post.cp_combo, "ending": post.ending}
        storage.append_jsonl(storage.DISTILLED_JSONL, [result])
        print("[{}/{}] 已蒸馏（{:.1f}s）：{}（{}）".format(
            i, len(todo), time.time() - t0, post.title or post.url, post.author))
        time.sleep(0.3)
    return len(todo)


def run_reduce(llm, cfg):
    entries = storage.load_jsonl(storage.DISTILLED_JSONL, dict_only=True)
    if not entries:
        raise SystemExit("distilled.jsonl 里没有数据")
    latest = {}
    for e in entries:  # 重跑会追加，取每个 post_id 最新一条
        latest[e.get("post_id") or e.get("url")] = e
    entries = [_compact(e) for e in latest.values()]

    batch_size = int(cfg.get("reduce_batch_size", 20))
    char_limit = int(cfg.get("batch_char_limit", 60000))
    focus = cfg.get("focus") or list(KNOWLEDGE_FILES.keys())

    # 按「文章类型·CP组合」分组，各自聚合出该分类的专属知识库；
    # 没有分类信息的旧数据归入「未分类」。
    groups = {}
    for e in entries:
        groups.setdefault(category_of(e.get("article_type"), e.get("cp_combo")), []).append(e)
    print("按分类聚合：" + "，".join(f"{k} {len(v)} 篇" for k, v in sorted(groups.items())))

    for cat, cat_entries in sorted(groups.items()):
        partials = []
        t0 = time.time()
        print("[{}] 正在聚合 {} 篇的提炼结果（一次大 LLM 调用，可能需要 1~3 分钟）…".format(
            cat, len(cat_entries)))
        if len(cat_entries) > batch_size:
            total_batches = (len(cat_entries) + batch_size - 1) // batch_size
            for bi in range(0, len(cat_entries), batch_size):
                batch = cat_entries[bi:bi + batch_size]
                chunks, used = [], 0
                for e in batch:
                    s = json.dumps(e, ensure_ascii=False)
                    if used + len(s) > char_limit:
                        break
                    chunks.append(s)
                    used += len(s)
                user = load_prompt(
                    "distill_reduce_partial",
                    schema=json.dumps(SCHEMA_EXAMPLE, ensure_ascii=False, indent=1),
                    articles="\n".join(chunks),
                )
                result = llm.chat_json(
                    system="你是同人文学资料整理员。只输出 JSON。",
                    user=user, temperature=0.2, timeout=300, retries=2,
                )
                partials.append(json.dumps(result, ensure_ascii=False))
                print("[{}] 聚合批次 {}/{} 完成（{:.0f}s）".format(
                    cat, len(partials), total_batches, time.time() - t0))
            reduce_input_name, reduce_input = "partials", "\n".join(partials)
        else:
            # 小分类一批就够，直接用原始提炼结果做最终合并，省一半调用
            reduce_input_name, reduce_input = "partials", "\n".join(
                json.dumps(e, ensure_ascii=False) for e in cat_entries)

        user = load_prompt("distill_reduce_final", **{reduce_input_name: reduce_input})
        final = llm.chat_json(
            system="你是同人文学资料整理员。只输出 JSON。",
            user=user, temperature=0.2, timeout=300, retries=2,
        )
        render_knowledge(final, focus, source_count=len(cat_entries), category=cat)
        print("[{}] 知识库生成完成，用时 {:.0f}s".format(cat, time.time() - t0))
    return len(entries)


def render_knowledge(final, focus, source_count=0, category=""):
    out_dir = storage.knowledge_dir(category)
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cat_note = f"（分类：{category}）" if category else ""
    head = ("<!-- 由蒸馏管道自动生成于 {}，素材来自 {} 篇{}文章的提炼结果。"
            "手工补充的内容会在下次蒸馏时被覆盖，建议在别处维护。 -->\n\n"
            .format(now, source_count, cat_note))

    # characters
    if "characters" in focus:
        lines = [head, "# 人设与关系知识库\n"]
        chars = final.get("characters") or []
        for c in chars:
            if not isinstance(c, dict):
                continue
            lines.append(f"## {c.get('name', '未知角色')}\n")
            traits = c.get("traits") or []
            if traits:
                lines.append("- 性格特征：" + "；".join(str(t) for t in traits))
            if c.get("speech"):
                lines.append("- 说话风格：" + str(c["speech"]))
            if c.get("dynamics"):
                lines.append("- 关系动态：" + str(c["dynamics"]))
            lines.append("")
        if len(lines) > 2:
            _write(out_dir, "characters", "\n".join(lines))

    if "style" in focus:
        lines = [head, "# 文风知识库\n", "按提及频次排序的写作风格特征：\n"]
        for item, cnt in _count(final.get("style")):
            lines.append(f"- {item}（{cnt} 篇提及）" if cnt > 1 else f"- {item}")
        if len(lines) > 3:
            _write(out_dir, "style", "\n".join(lines))

    if "tropes" in focus:
        lines = [head, "# 桥段与爽点知识库\n", "按出现频次排序：\n"]
        counted = Counter()
        detail_map = {}
        for t in final.get("tropes") or []:
            if isinstance(t, dict) and t.get("name"):
                name = str(t["name"]).strip()
                counted[name] += 1
                detail_map.setdefault(name, str(t.get("detail", "")).strip())
            elif isinstance(t, str):
                counted[t] += 1
        for name, cnt in counted.most_common():
            detail = detail_map.get(name, "")
            prefix = f"（{cnt} 篇出现）" if cnt > 1 else ""
            lines.append(f"## {name} {prefix}\n\n{detail}\n" if detail
                         else f"- {name} {prefix}")
        if len(lines) > 3:
            _write(out_dir, "tropes", "\n".join(lines))

    if "warnings" in focus:
        lines = [head, "# 雷点清单\n", "写作时应规避：\n"]
        for item, cnt in _count(final.get("warnings")):
            lines.append(f"- {item}（{cnt} 篇提及）" if cnt > 1 else f"- {item}")
        if len(lines) > 3:
            _write(out_dir, "warnings", "\n".join(lines))

    print("知识库已生成到 {}：{}".format(
        out_dir, ", ".join(KNOWLEDGE_FILES[k] for k in focus if k in KNOWLEDGE_FILES)))


def _count(items):
    return Counter(str(x).strip() for x in (items or []) if str(x).strip()).most_common()


def _write(out_dir, key, content):
    path = os.path.join(out_dir, KNOWLEDGE_FILES[key])
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def run_distill(cfg, llm=None):
    """cfg 兼容两种形态：完整配置（含 models 段）或 distill 子段。

    分阶段模型必须从顶层 models 段取——早先 main.py 只传 distill 子段，
    导致 distill_map/distill_reduce 配了也不生效。
    """
    full = cfg if isinstance(cfg, dict) else {}
    dcfg = full.get("distill") if isinstance(full.get("distill"), dict) else full
    models = full.get("models") or dcfg.get("models") or {}
    llm = llm or LLMClient()
    # 分阶段模型：提炼量大用便宜的，聚合质量敏感可用强模型
    map_llm = llm_for(models.get("distill_map"), llm, full.get("providers"))
    reduce_llm = llm_for(models.get("distill_reduce"), llm, full.get("providers"))
    if map_llm.model != reduce_llm.model:
        print("模型分配：提炼用 {}，聚合用 {}".format(map_llm.model, reduce_llm.model))
    n_map = run_map(map_llm, dcfg)
    n_reduce = run_reduce(reduce_llm, dcfg)
    print("蒸馏完成：本次新增 {} 篇提炼，聚合素材共 {} 篇".format(n_map, n_reduce))

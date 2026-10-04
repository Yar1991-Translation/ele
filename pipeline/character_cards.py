"""蒸馏人物卡：从已下载的同人文中深度蒸馏每个角色的同人形象。

流程：
  1. 角色发现：扫 distilled.jsonl 的提炼结果，按角色名聚合计数，
     出现 >= min_mentions 篇的角色建卡；
  2. 深度蒸馏：每角色重读提到它的原文全文，按字数分批；
  3. 并发提炼：模型支持多并发——所有角色的所有批次用线程池并行请求，
     之后再对每个角色并发合并分批结果；
  4. 产出：data/personas_distilled/<角色名>.md，头部标注来源篇数与日期；
  5. 增量缓存：按"来源文章集合指纹"跳过未变化的角色。
"""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm.client import LLMClient, llm_for
from llm.prompts import load_prompt
from spider import storage


def _normalize(name):
    """角色名归一：去作品后缀与空白。"""
    n = (name or "").strip()
    for suf in ("(三角洲行动)", "（三角洲行动）"):
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return n


def discover_characters(min_mentions):
    """从 distilled.jsonl 聚合角色与文章映射。

    返回 [(角色名, [post_id...])]，按提及篇数降序。
    """
    entries = storage.load_jsonl(storage.DISTILLED_JSONL, dict_only=True)
    counter, posts_by_char = {}, {}
    for e in entries:
        pid = e.get("post_id") or e.get("url")
        if not pid:
            continue
        for c in e.get("characters") or []:
            if not isinstance(c, dict):
                continue
            name = _normalize(c.get("name"))
            if not name or _is_noise_name(name):
                continue
            counter[name] = counter.get(name, 0) + 1
            posts_by_char.setdefault(name, set()).add(pid)
    qualified = [(n, sorted(posts_by_char[n])) for n, cnt in counter.items()
                 if cnt >= min_mentions]
    qualified.sort(key=lambda x: -counter[x[0]])
    return qualified, counter, posts_by_char


def _is_noise_name(name):
    """过滤提炼噪声：群体描述、超长描述性"名字"不是角色。"""
    if len(name) > 12:
        return True
    if name.startswith(("其他", "众人", "大家", "队友们")):
        return True
    if "等" in name and name.endswith(("）", ")")):
        return True
    return False


ALIAS_CACHE = os.path.join(storage.DATA_DIR, "alias_groups.json")


def resolve_aliases(counter, posts_by_char, llm, official_names=None):
    """LLM 别名归组：把本名/代号/译名等同一角色的名字并成一组。

    结果缓存 data/alias_groups.json（按名字集合指纹）。
    代表名优先取官方人物卡里存在的名字（回响 优先于 卢克），
    否则取组内提及最多者。
    返回 ([(代表名, 合并后的 post_id 集)], groups)。
    """
    official_names = official_names or set()
    names = sorted(counter)
    fp = hashlib.md5(json.dumps(names, ensure_ascii=False).encode("utf-8")).hexdigest()
    groups = None
    if os.path.exists(ALIAS_CACHE):
        try:
            with open(ALIAS_CACHE, encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fingerprint") == fp:
                groups = cached.get("groups")
        except (json.JSONDecodeError, OSError):
            pass
    if groups is None:
        print("别名归组：请 LLM 判断哪些名字是同一角色…")
        user = ("下面是某同人圈子里出现的角色名清单（含提及次数）。请把明显是同一角色的"
                "名字分到一组——本名/代号/译名/昵称/错别字变体都算同一角色。"
                "拿不准的独立成组，不要强行合并。\n\n角色名清单：\n"
                + "\n".join(f"- {n}（{counter[n]} 篇）" for n in names)
                + "\n\n只输出 JSON：{\"groups\": [[\"代表名\",\"别名\",…], …]}，"
                  "每组第一个名字作为代表名。")
        result = llm.chat_json(
            system="你是同人圈考据助手。只输出 JSON。",
            user=user, temperature=0.1, timeout=120, retries=2)
        groups = result.get("groups") or []
        if not isinstance(groups, list):
            groups = []
        os.makedirs(os.path.dirname(ALIAS_CACHE), exist_ok=True)
        with open(ALIAS_CACHE, "w", encoding="utf-8") as f:
            json.dump({"fingerprint": fp, "groups": groups}, f, ensure_ascii=False, indent=1)
    merged = {}
    for g in groups:
        if not isinstance(g, list) or not g:
            continue
        members = [_normalize(str(n)) for n in g if str(n).strip()]
        members = [n for n in members if counter.get(n)]
        if not members:
            continue
        # 代表名：优先官方人物卡里的名字，其次提及最多者
        rep = next((n for n in members if n in official_names), None)
        if rep is None:
            rep = max(members, key=lambda n: counter.get(n, 0))
        ids = set()
        for n in members:
            ids |= posts_by_char.get(n, set())
        if ids:
            merged[rep] = ids
    grouped = {str(n) for g in groups for n in g} if groups else set()
    for n in names:   # 兜底：没进任何组的名字单独保留
        if n not in grouped and counter.get(n):
            merged.setdefault(n, posts_by_char.get(n, set()))
    out = [(n, ids) for n, ids in merged.items() if ids]
    out.sort(key=lambda x: -len(x[1]))
    return out, groups


def _load_article_texts(post_ids, article_input_limit):
    """按 post_id 从 filtered/posts 里取原文全文。"""
    pool = {}
    for path in (storage.FILTERED_JSONL, storage.POSTS_JSONL):
        if not os.path.exists(path):
            continue
        for d in storage.load_jsonl(path, dict_only=True):
            pid = d.get("post_id") or d.get("url")
            if pid in post_ids and pid not in pool:
                text = (d.get("long_text") or d.get("content_md") or "").strip()
                if text:
                    pool[pid] = {"title": d.get("title") or "（无标题）",
                                 "text": text[:article_input_limit]}
    return pool


def _fingerprint(post_ids):
    return hashlib.md5(json.dumps(sorted(post_ids), ensure_ascii=False)
                       .encode("utf-8")).hexdigest()


def _batches(articles, batch_chars):
    """把文章按总字数装箱成批。"""
    batches, cur, cur_len = [], [], 0
    for a in articles:
        size = len(a["text"])
        if cur and cur_len + size > batch_chars:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(a)
        cur_len += size
    if cur:
        batches.append(cur)
    return batches


def _batch_text(batch):
    return "\n\n".join(f"《{a['title']}》\n{a['text']}" for a in batch)


def _render_card(name, merged, n_articles):
    day = time.strftime("%Y-%m-%d")
    lines = [
        f"# {name}",
        "",
        f"> 蒸馏人物卡：来自 {n_articles} 篇同人文的深度提炼，检索于 {day}。",
        "> 这是**同人语境形象**（含圈内自设倾向），与官方档案相互独立；",
        "> 写作时与本目录其他蒸馏卡共同使用，塑造人物以此层为主。",
        "",
        "## 同人形象共识",
        "",
    ]
    for x in merged.get("consensus") or []:
        lines.append(f"- {x}")
    lines += ["", "## 性格与说话方式", ""]
    for x in merged.get("speech") or []:
        lines.append(f"- {x}")
    lines += ["", "## 与其他角色的关系", ""]
    for x in merged.get("relationships") or []:
        lines.append(f"- {x}")
    lines += ["", "## 常见情节设定（自设倾向）", ""]
    for x in merged.get("plot_tropes") or []:
        lines.append(f"- {x}")
    lines += ["", "## 与官方设定的差异", ""]
    for x in merged.get("divergence_official") or []:
        lines.append(f"- {x}")
    return "\n".join(lines).strip() + "\n"


def run_character_cards(cfg, llm=None, only=None):
    """主入口：深度蒸馏全部合格角色。返回 (完成数, 跳过数, 失败列表)。"""
    ccfg = (cfg.get("character_cards") or {}) if isinstance(cfg, dict) else {}
    llm = llm_for((cfg.get("models") or {}).get("character_cards") if isinstance(cfg, dict) else "",
                  llm, cfg.get("providers") if isinstance(cfg, dict) else None)
    min_mentions = int(ccfg.get("min_mentions", 2) or 2)
    max_articles = int(ccfg.get("max_articles_per_char", 12) or 12)
    batch_chars = int(ccfg.get("batch_article_chars", 12000) or 12000)
    article_limit = int(ccfg.get("article_input_limit", 8000) or 8000)
    concurrency = max(1, int(ccfg.get("concurrency", 3) or 3))

    chars_raw, counter, posts_by_char = discover_characters(min_mentions)
    official_names = {p["name"] for p in storage.parse_personas()}
    chars, groups = resolve_aliases(counter, posts_by_char, llm, official_names)
    # 别名组里非代表名的旧卡片文件清理（如上次跑出的"卢克.md"）
    for g in groups:
        if not isinstance(g, list):
            continue
        members = [_normalize(str(n)) for n in g if str(n).strip()]
        reps = [n for n, _ in chars]
        rep_here = next((n for n in reps if n in members), None)
        if rep_here:
            for alias in members:
                if alias != rep_here:
                    old = os.path.join(storage.PERSONAS_DISTILLED_DIR,
                                       storage._safe_name(alias) + ".md")
                    if os.path.isfile(old):
                        os.remove(old)
                        print("  已移除别名旧卡：{}".format(alias))
    if only:
        want = {only}
        matched = [c for c in chars if c[0] in want]
        chars = matched or [(only, [])]   # 指定角色即使不足门槛也强制建卡
    if not chars:
        print("没有达到建卡门槛的角色（min_mentions={}）".format(min_mentions))
        return (0, 0, [])

    cache = storage.load_char_cache()
    storage.ensure_dirs()
    keep_cards = set()        # 本轮有效（重写或缓存命中）的卡片文件

    # 组装任务并按缓存指纹跳过未变化的角色
    tasks, skipped = {}, 0
    for name, post_ids in chars:
        ids = set(list(post_ids)[:max_articles])
        fp = _fingerprint(ids)
        cached = cache.get(name)
        if cached and cached.get("fingerprint") == fp and not only:
            skipped += 1
            if cached.get("card"):
                keep_cards.add(cached["card"])
            continue
        texts = _load_article_texts(ids, article_limit)
        if not texts:
            skipped += 1
            continue
        tasks[name] = (list(texts.values()), fp)

    if skipped:
        print("缓存命中跳过 {} 个角色".format(skipped))
    if not tasks:
        print("全部角色均为最新，无需重新蒸馏")
        return (0, skipped, [])

    # 阶段一：并发分批提炼（跨角色、跨批次统一进线程池）
    jobs = []          # (角色名, 批次序号, 批次文章)
    batch_counts = {}
    for name, (articles, fp) in tasks.items():
        valid = [b for b in _batches(articles, batch_chars)
                 if len(_batch_text(b).strip()) >= 200]   # 空片段批次直接跳过
        if not valid:
            print("  [{}] 没有可用的原文片段（文章可能在被排除堆里），跳过".format(name))
            continue
        batch_counts[name] = len(valid)
        for bi, batch in enumerate(valid):
            jobs.append((name, bi, batch))
    partials = {name: [None] * batch_counts[name] for name in batch_counts}

    print("深度蒸馏：{} 个角色、{} 个批次，并发 {}…".format(
        len(tasks), len(jobs), concurrency))
    failed = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {}
        for name, bi, batch in jobs:
            user = load_prompt("character_deep_map", char=name,
                               articles=_batch_text(batch))
            futs[pool.submit(llm.chat_json,
                             system="你是同人文学分析师。只输出 JSON。",
                             user=user, temperature=0.3, timeout=300, retries=2)] = (name, bi)
        for fut in as_completed(futs):
            name, bi = futs[fut]
            try:
                partials[name][bi] = fut.result()
                done = sum(1 for x in partials[name] if x is not None)
                print("  [{}] 批次 {}/{} 提炼完成".format(name, done, batch_counts[name]))
            except Exception as e:  # noqa: BLE001 单批失败不阻塞
                failed.append((name, "批次{}".format(bi + 1), str(e)[:80]))
                print("  [{}] 批次 {} 失败：{}".format(name, bi + 1, str(e)[:80]))

    # 阶段二：并发合并成卡（只处理阶段一有有效批次的角色）
    merge_jobs = [(name, [p for p in partials[name] if p])
                  for name in partials if any(partials[name])]
    done_n = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {}
        for name, parts in merge_jobs:
            user = load_prompt("character_deep_merge", char=name,
                               partials=json.dumps(parts, ensure_ascii=False, indent=1))
            futs[pool.submit(llm.chat_json,
                             system="你是同人文学资料整理员。只输出 JSON。",
                             user=user, temperature=0.3, timeout=300, retries=2)] = name
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                merged = fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append((name, "合并", str(e)[:80]))
                print("  [{}] 合并失败：{}".format(name, str(e)[:80]))
                continue
            card = _render_card(name, merged, len(tasks[name][0]))
            fname = storage._safe_name(name) + ".md"
            with open(os.path.join(storage.PERSONAS_DISTILLED_DIR, fname),
                      "w", encoding="utf-8") as f:
                f.write(card)
            cache[name] = {"name": name, "fingerprint": tasks[name][1], "card": fname}
            storage.save_char_cache(cache)
            keep_cards.add(fname)
            done_n += 1
            print("  [{}] 蒸馏人物卡已生成（{} 字）".format(name, len(card)))

    if not only:   # 清理上一轮遗留的孤儿卡（噪声名/别名旧卡/已删除角色）
        for fn in storage.distilled_card_files():
            if fn not in keep_cards:
                os.remove(os.path.join(storage.PERSONAS_DISTILLED_DIR, fn))
                print("  已清理孤儿卡：{}".format(fn))
    return (done_n, skipped, failed)

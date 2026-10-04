"""乙女向过滤 + 文章分类：第一层关键词直接排除，第二层 LLM 判定并分类。

一次 LLM 调用同时完成乙女向判定和文章分类（文章类型/CP组合/结局），
结果随 filtered.jsonl 传给蒸馏阶段——蒸馏按「文章类型·CP组合」分组建
知识库，写作时按目标类型直接取用。

结构：先跑完全部关键词（不花钱），再对剩余文章逐篇调 LLM（每篇都打
进度和耗时，单次调用 60s 超时、快速失败；连续 3 篇失败就熔断退出——
成功的判定都缓存在 filter_cache.json，修复后重跑只处理剩余的）。
"""
import json
import os
import time

from llm.client import LLMClient, LLMError, llm_for
from llm.prompts import load_prompt
from spider import storage
from spider.models import ARTICLE_TYPES, CP_COMBOS, ENDINGS, Post

CACHE_PATH = os.path.join(storage.DATA_DIR, "posts", "filter_cache.json")
CACHE_VERSION = 2
JUDGE_TIMEOUT = 60       # 单篇判定的请求超时（秒）
JUDGE_RETRIES = 2        # 单篇失败快速重试次数
BREAKER_LIMIT = 3        # 连续失败多少篇就熔断


def normalize_classification(raw):
    """把 LLM 返回的分类规范到合法枚举；缺失/非法给默认值。

    规则：单人向强制 CP组合=微量。
    """
    raw = raw if isinstance(raw, dict) else {}
    t = str(raw.get("article_type", "")).strip()
    c = str(raw.get("cp_combo", "")).strip()
    e = str(raw.get("ending", "")).strip()
    if t not in ARTICLE_TYPES:
        t = "其他"
    if c not in CP_COMBOS:
        c = "微量"
    if e not in ENDINGS:
        e = "未知"
    if t == "单人向":
        c = "微量"
    return {"article_type": t, "cp_combo": c, "ending": e}


def _keyword_hit(post: Post, keywords):
    head = post.text[:800] if post.text else ""
    for kw in keywords:
        if kw in post.title or kw in head or any(kw in t for t in post.tags):
            return kw
    return None


def _llm_judge(llm, post: Post, sample_chars, threshold):
    sample = post.text[:sample_chars] if post.text else "（无正文，可能为图片帖）"
    user = load_prompt("filter_otome", article=(
        f"标题：{post.title or '（无）'}\n"
        f"tags：{', '.join(post.tags) if post.tags else '无'}\n"
        f"正文开头：\n{sample}"
    ))
    result = llm.chat_json(
        system="你是准确、稳定的同人内容分类器，只输出 JSON。",
        user=user, temperature=0.1,
        timeout=JUDGE_TIMEOUT, retries=JUDGE_RETRIES,
    )
    cls = normalize_classification(result)
    otome = bool(result.get("otome", False))
    try:
        confidence = float(result.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(result.get("reason", ""))[:200]
    return otome and confidence >= threshold, reason, cls


def run_filter(cfg, llm=None):
    posts = storage.load_posts()
    if not posts:
        raise SystemExit("posts.jsonl 里没有数据，请先运行 python main.py crawl")

    fcfg = cfg.get("filter", {})
    keywords = fcfg.get("keywords") or []
    llm_judge_on = bool(fcfg.get("llm_judge", True))
    threshold = float(fcfg.get("confidence_threshold", 0.6))
    sample_chars = int(fcfg.get("content_sample_chars", 600))
    text_only = bool(fcfg.get("text_only", True))       # 只保留纯文字帖（排除图片帖）
    min_length = int(fcfg.get("min_length", 300) or 0)  # 正文最少字数（碎片帖排除）

    print("开始过滤：读入 {} 篇，先跑门槛层（图片帖/碎片帖）与关键词层，"
          "再对剩余文章逐篇 LLM 判定…".format(len(posts)))

    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        except json.JSONDecodeError:
            cache = {}

    # ---- 第零层：长度与图片门槛（零成本，先跑）----
    excluded, to_judge = [], []
    for post in posts:
        if text_only and post.images:
            excluded.append({**post.to_dict(),
                             "exclude_reason": "图片帖（text_only 模式只保留纯文字帖）"})
            continue
        if len(post.text.strip()) < min_length:
            excluded.append({**post.to_dict(),
                             "exclude_reason": f"正文不足 {min_length} 字（碎片帖）"})
            continue
        kw = _keyword_hit(post, keywords)
        if kw:
            excluded.append({**post.to_dict(), "exclude_reason": f"关键词命中「{kw}」"})
        else:
            to_judge.append(post)
    print("门槛层完成：图片帖/碎片帖共排除 {} 篇，剩余 {} 篇".format(len(excluded), len(to_judge)))

    # ---- 第二层：LLM 判定 + 分类 ----
    kept = []
    if llm_judge_on and to_judge:
        llm = llm_for(cfg.get("models", {}).get("filter"), llm, cfg.get("providers"))
        cached_n = sum(1 for p in to_judge
                       if cache.get(p.url, {}).get("v") == CACHE_VERSION)
        print("LLM 判定 {} 篇（其中 {} 篇有缓存），每篇一行进度；单次调用 60s 超时，"
              "连续 3 篇失败自动熔断".format(len(to_judge), cached_n))
        started = time.time()
        billed = 0          # 本次实际调用 LLM 的篇数（缓存命中不计）
        consec_fail = 0
        for i, post in enumerate(to_judge, 1):
            cached = cache.get(post.url)
            cache_hit = cached is not None and cached.get("v") == CACHE_VERSION
            judge_failed = False
            dt = 0.0
            if cache_hit:
                hit, reason, cls = cached["hit"], cached["reason"], cached["classification"]
            else:
                t0 = time.time()
                try:
                    hit, reason, cls = _llm_judge(llm, post, sample_chars, threshold)
                except LLMError as e:
                    judge_failed = True
                    consec_fail += 1
                    if consec_fail >= BREAKER_LIMIT:
                        raise SystemExit(
                            f"LLM 连续 {consec_fail} 篇判定失败，已熔断（最后错误：{e}）。\n"
                            "请检查 .env 的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 和网络，"
                            "修复后重跑——已成功的判定有缓存，只会处理剩余的。")
                    print(f"  [{i}/{len(to_judge)}] 判定失败（{str(e)[:120]}），本篇暂保留，可重跑补判")
                    hit, reason, cls = False, "LLM判定失败，暂保留", normalize_classification({})
                else:
                    consec_fail = 0
                    cache[post.url] = {"v": CACHE_VERSION, "hit": hit,
                                       "reason": reason, "classification": cls}
                    time.sleep(0.3)  # 对 LLM 服务温柔一点
                dt = time.time() - t0
                billed += 1

            if hit:
                excluded.append({**post.to_dict(), "exclude_reason": reason})
            else:
                post.article_type, post.cp_combo, post.ending = (
                    cls["article_type"], cls["cp_combo"], cls["ending"])
                kept.append(post)

            if judge_failed:
                print("  [{}/{}] 暂保留（LLM 失败，重跑补判）：{}".format(
                    i, len(to_judge), post.title or post.url))
            elif cache_hit:
                print("  [{}/{}] {}（缓存）：{}".format(
                    i, len(to_judge), "排除" if hit else "保留", post.title or post.url))
            else:
                if billed:
                    avg = (time.time() - started) / billed
                    eta = (len(to_judge) - i) * avg / 60
                    print("  [{}/{}] {}（{:.1f}s，均 {:.1f}s/篇，预计还需 {:.0f} 分钟）：{}".format(
                        i, len(to_judge), "排除" if hit else "保留", dt, avg, eta,
                        post.title or post.url))
                else:
                    # billed=0：此前全是图片帖/缓存等不经过 LLM 的分支
                    print("  [{}/{}] {}：{}".format(
                        i, len(to_judge), "排除" if hit else "保留", post.title or post.url))
    else:
        kept = to_judge  # 不启用 LLM 层：全部保留、无分类

    os.makedirs(os.path.dirname(storage.FILTERED_JSONL), exist_ok=True)
    with open(storage.FILTERED_JSONL, "w", encoding="utf-8") as f:
        for p in kept:
            f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")
    with open(storage.EXCLUDED_JSONL, "w", encoding="utf-8") as f:
        for p in excluded:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)

    type_counter = {}
    for p in kept:
        if p.article_type:
            type_counter[p.article_type] = type_counter.get(p.article_type, 0) + 1
    print("过滤完成：保留 {} 篇 -> filtered.jsonl；排除 {} 篇 -> excluded.jsonl（可人工复查）"
          .format(len(kept), len(excluded)))
    if type_counter:
        print("分类统计：" + "，".join(f"{k} {v} 篇" for k, v in sorted(type_counter.items())))
    return len(kept), len(excluded)

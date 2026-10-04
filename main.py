"""lofter-tag-distiller：爬取 -> 过滤乙女向 -> LLM 蒸馏 -> 按想法写作。

用法：
    python main.py crawl            # 1. 爬取 tag 下的文章
    python main.py filter           # 2. 过滤乙女向
    python main.py distill          # 3. 蒸馏成知识库
    python main.py write -i "想法"  # 4. 按想法写一篇文章
    python main.py run-all          # 1->2->3 一键
    python main.py stats            # 查看各阶段数据量
    python main.py selftest         # 离线自测解析器（不需要网络和配置）
"""
import argparse
import os
import sys

# Windows 控制台中文输出保护
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

load_dotenv()

import yaml  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config():
    from gui.config_schema import write_defaults_if_missing
    path = os.path.join(ROOT, "config.yaml")
    write_defaults_if_missing(path)   # 新克隆/新机器：没有 config.yaml 就按默认值生成
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_cookie_kwargs():
    from dotenv import dotenv_values
    vals = dotenv_values(os.path.join(ROOT, ".env")) if os.path.exists(
        os.path.join(ROOT, ".env")) else {}
    cookie = (vals.get("LOFTER_COOKIE") or "").strip()
    login_key = (vals.get("LOFTER_LOGIN_KEY") or "").strip()
    login_auth = (vals.get("LOFTER_LOGIN_AUTH") or "").strip()
    if not cookie and not (login_key and login_auth):
        raise SystemExit(
            "还没有配置 Lofter 登录信息：复制 .env.example 为 .env，\n"
            "按其中说明填 LOFTER_COOKIE（推荐，浏览器 F12 复制整行 Cookie）\n"
            "或 LOFTER_LOGIN_KEY + LOFTER_LOGIN_AUTH。"
        )
    return {"cookie": cookie or None,
            "login_key": login_key or None,
            "login_auth": login_auth or None}


def print_usage_stats():
    from llm.client import usage_stats
    if not usage_stats["calls"]:
        return
    print("LLM 用量：{} 次调用，输入 {} tokens，输出 {} tokens".format(
        usage_stats["calls"], usage_stats["prompt_tokens"], usage_stats["completion_tokens"]))
    by_model = usage_stats.get("by_model") or {}
    if len(by_model) > 1:   # 多模型时打印分模型明细，便于核对各家花了多少
        for name, s in sorted(by_model.items()):
            print("  · {}：{} 次，输入 {}，输出 {}".format(
                name, s["calls"], s["prompt_tokens"], s["completion_tokens"]))


# ----------------------------------------------------------------------
def cmd_crawl(args):
    from spider.fetcher import Crawler
    cfg = load_config()
    Crawler(cfg.get("crawl", {}), force_login_check=args.force,
            **get_cookie_kwargs()).run()


def cmd_filter(args):
    from pipeline.filter_otome import run_filter
    run_filter(load_config())


def cmd_distill(args):
    from pipeline.distill import run_distill
    # 传完整配置：分阶段模型在顶层 models 段，只传 distill 子段会让其配了不生效
    run_distill(load_config())


def cmd_write(args):
    from pipeline.writer import write_article
    cfg = load_config()
    mode = args.mode or "auto"
    draft = ""
    if mode not in ("auto", "quick"):
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                draft = f.read()
        elif args.draft:
            draft = args.draft
        if not draft.strip():
            raise SystemExit("「{}」方式需要原稿：用 --file 文件 或 --draft 内联文本提供".format(mode))
    idea = (args.idea or "").strip()
    if mode in ("auto", "quick") and not idea:
        idea = input("请输入你的想法（快速模式填一个关键词或一句话即可，越具体越好）：\n> ").strip()
    if mode in ("auto", "quick") and not idea:
        raise SystemExit("想法不能为空")
    write_article(idea, cfg, article_type=args.type, cp_combo=args.cp,
                  ending=args.ending, mode=mode, draft=draft,
                  persona_source=args.persona_source,
                  official_weight=args.official_weight,
                  roster_all=args.all_roster, rating=args.rating)


def cmd_run_all(args):
    cmd_crawl(args)
    cmd_filter(args)
    cmd_distill(args)
    print("\n素材已就绪！接下来运行：python main.py write -i \"你的想法\"")


def cmd_wiki_import(args):
    from pipeline.wiki_import import import_category
    results = import_category(args.category, limit=args.limit,
                              card_max_chars=args.card_chars)
    ok = sum(1 for _, _, a in results if a == "ok")
    skip = sum(1 for _, _, a in results if a == "skip")
    fail = [t for t, _, a in results if a == "fail"]
    print(f"导入完成：新增 {ok}，已存在跳过 {skip}，失败 {len(fail)}"
          + (f"（{('、'.join(fail))}）" if fail else ""))


def cmd_personas(args):
    from spider import storage
    if args.action == "import":
        import shutil
        if not args.path:
            raise SystemExit("import 需要路径：python main.py personas import <文件或文件夹>")
        src = os.path.abspath(args.path)
        if os.path.isfile(src):
            files = [src]
        elif os.path.isdir(src):
            files = [os.path.join(src, f) for f in sorted(os.listdir(src))
                     if f.lower().endswith((".md", ".txt"))]
        else:
            raise SystemExit(f"路径不存在：{src}")
        if not files:
            raise SystemExit("没找到 .md/.txt 文件")
        os.makedirs(storage.PERSONAS_DIR, exist_ok=True)
        for f in files:
            shutil.copyfile(f, os.path.join(storage.PERSONAS_DIR, os.path.basename(f)))
            print("已导入", os.path.basename(f))
        print(f"共导入 {len(files)} 份 -> {storage.PERSONAS_DIR}")
    elif args.action == "list":
        ps = storage.parse_personas()
        if not ps:
            print("（data/personas/ 为空）用 personas import 导入，或直接把 .md/.txt 丢进该目录")
        cur = None
        for p_ in ps:
            if p_["file"] != cur:
                cur = p_["file"]
                print(f"- {cur}")
            print(f"    · {p_['name']}（{len(p_['content'])} 字）")
    elif args.action == "remove":
        if not args.path:
            raise SystemExit("remove 需要文件名：python main.py personas remove <文件名>")
        dst = os.path.join(storage.PERSONAS_DIR, os.path.basename(args.path))
        if os.path.exists(dst):
            os.remove(dst)
            print("已删除", args.path)
        else:
            raise SystemExit(f"文件不存在：{dst}")


def cmd_distill_characters(args):
    from pipeline.character_cards import run_character_cards
    cfg = load_config()
    done, skipped, failed = run_character_cards(cfg, only=args.only)
    print(f"角色卡蒸馏完成：新增 {done}，缓存跳过 {skipped}，失败 {len(failed)}"
          + (f"（{'、'.join(n for n, _, _ in failed)}）" if failed else ""))


def cmd_stats(args):
    from spider import storage
    def n(path):
        return len(storage.load_jsonl(path, dict_only=True)) if os.path.exists(path) else 0
    print("爬取 posts.jsonl    ：{} 篇".format(n(storage.POSTS_JSONL)))
    print("过滤 filtered.jsonl ：{} 篇".format(n(storage.FILTERED_JSONL)))
    print("排除 excluded.jsonl ：{} 篇".format(n(storage.EXCLUDED_JSONL)))
    print("蒸馏 distilled.jsonl：{} 篇".format(n(storage.DISTILLED_JSONL)))
    if os.path.isdir(storage.KNOWLEDGE_DIR):
        ks = []
        for d in sorted(os.listdir(storage.KNOWLEDGE_DIR)):
            sub = os.path.join(storage.KNOWLEDGE_DIR, d)
            if os.path.isdir(sub):
                ks.extend(f"{d}/{f[:-3]}" for f in sorted(os.listdir(sub)) if f.endswith(".md"))
            elif d.endswith(".md"):
                ks.append(d[:-3])
        print("知识库              ：{} 套 -> {}".format(
            len({k.split('/')[0] for k in ks}), ", ".join(ks) if ks else "（空）"))
    else:
        print("知识库              ：（未生成）")
    if os.path.isdir(storage.OUTPUT_DIR):
        os_ = [f for f in os.listdir(storage.OUTPUT_DIR) if f.endswith(".md")]
        print("已生成文章          ：{} 篇".format(len(os_)))


def cmd_selftest(args):
    from spider.parser import extract_posts, js_unescape
    sample_path = os.path.join(ROOT, "tests", "sample_dwr.txt")
    with open(sample_path, encoding="utf-8") as f:
        text = f.read()

    assert js_unescape("a\\u4e2db") == "a中b"
    assert js_unescape("\\ud83d\\ude00") == "\U0001f600"
    assert js_unescape('say \\"hi\\" \\\\ \\/') == 'say "hi" \\ /'

    posts = extract_posts(text, "测试tag")
    assert len(posts) == 3, f"应提取出 3 篇帖子，实际 {len(posts)}"

    by_id = {p.post_id: p for p in posts}
    p1 = by_id["1e5f3a_1234567"]
    assert p1.title == "深夜标题", p1.title
    assert p1.author == "某某某", p1.author
    assert p1.tags == ["原作", "同人文"], p1.tags
    assert p1.hot == 88 and p1.publish_time, (p1.hot, p1.publish_time)
    assert 'hello 世界 "quote" ;' in p1.content_md, p1.content_md
    assert "😀" in p1.content_md, "emoji 代理对应还原"
    assert p1.post_type == "article", p1.post_type

    p2 = by_id["2b6c4d_7654321"]
    assert p2.post_type == "long" and "长文第一章" in p2.long_text, (p2.post_type, p2.long_text[:50])
    assert p2.author == "长文作者", p2.author

    p3 = by_id["3c7d5e_1112223"]
    assert p3.post_type == "img" and len(p3.images) == 1, (p3.post_type, p3.images)
    assert p3.images[0].startswith("https://imglf1.lf127.net/img/")

    print("selftest 全部通过：分词器、转义还原、代理对、帖子提取、类型分类均正常")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("crawl", help="爬取 tag 下的文章")
    p.add_argument("--force", action="store_true", help="跳过登录检查")
    p.set_defaults(func=cmd_crawl)

    p = sub.add_parser("filter", help="过滤乙女向文章")
    p.set_defaults(func=cmd_filter)

    p = sub.add_parser("distill", help="蒸馏成知识库")
    p.set_defaults(func=cmd_distill)

    p = sub.add_parser("write", help="根据想法写一篇文章")
    p.add_argument("-i", "--idea", help="你想看的文章的想法/要求")
    p.add_argument("--type", dest="type", choices=["单人向", "CP向", "其他"],
                   help="文章类型（默认取 config）")
    p.add_argument("--cp", dest="cp",
                   choices=["微量", "男女", "男男", "女女", "多CP", "无CP"],
                   help="CP组合；文章类型为单人向时强制微量")
    p.add_argument("--ending", choices=["HE", "BE", "开放式", "不限"],
                   help="结局走向（默认取 config）")
    p.add_argument("--mode", choices=["auto", "quick", "self", "polish", "expand", "team"],
                   default="auto",
                   help="写作方式：auto=自动生成 quick=关键词速写（关键词+人物点名"
                        "[--all-roster 全员客串]） self=我自己写 polish=润色 "
                        "expand=扩充 team=多Agent团队讨论润色")
    p.add_argument("--file", help="原稿文件路径（self/polish/expand 模式用）")
    p.add_argument("--draft", help="原稿内联文本（短稿可用，长稿建议 --file）")
    p.add_argument("--all-roster", action="store_true",
                   help="快速模式（quick）：除已点名角色外，官方名单全员以跑龙套客串")
    p.add_argument("--rating", choices=["r12", "r16", "r18", "r18g"],
                   help="内容分级：r12=全年龄 r16=辅导级 r18=限制级 r18g=含残酷描写"
                        "（默认取 config，兜底 r12）")
    p.add_argument("--persona-source", choices=["both", "distilled", "official"],
                   help="人物卡来源：both=官方+蒸馏 both=两者结合（默认）")
    p.add_argument("--official-weight", type=int, help="官方档案权重 0~100（蒸馏=100-该值，默认 30）")
    p.set_defaults(func=cmd_write)

    p = sub.add_parser("run-all", help="爬取->过滤->蒸馏 一键运行")
    p.add_argument("--force", action="store_true", help="跳过登录检查")
    p.set_defaults(func=cmd_run_all)

    p = sub.add_parser("stats", help="查看各阶段数据量")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("wiki-import", help="从萌娘百科分类导入角色资料为人物卡")
    p.add_argument("--category", required=True, help="萌娘百科分类名，如：三角洲行动")
    p.add_argument("--limit", type=int, default=60, help="最多导入多少个页面")
    p.add_argument("--card-chars", type=int, default=6000, help="每张人物卡的最大字符数")
    p.set_defaults(func=cmd_wiki_import)

    p = sub.add_parser("personas", help="本地角色人设导入管理")
    p.add_argument("action", choices=["import", "list", "remove"],
                   help="import=导入文件/文件夹  list=查看  remove=删除")
    p.add_argument("path", nargs="?", help="import 的来源路径 / remove 的文件名")
    p.set_defaults(func=cmd_personas)

    p = sub.add_parser("distill-characters", help="深度蒸馏人物卡（重读原文）")
    p.add_argument("--only", help="只蒸馏指定角色名")
    p.set_defaults(func=cmd_distill_characters)

    p = sub.add_parser("selftest", help="离线自测解析器")
    p.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    try:
        args.func(args)
    finally:
        print_usage_stats()


if __name__ == "__main__":
    main()

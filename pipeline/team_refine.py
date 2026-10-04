"""Agent 团队润色：多位"编辑"（可配不同模型/思考强度）多轮评审讨论，主笔汇总修订。

流程（每轮）：
  1. 全体成员各评审一次当前稿（能看到其他成员本轮已发表的意见，可补充/反驳）；
  2. 主笔（editor_model，留空=主模型）汇总意见，产出修订稿；
  3. 修订稿进入下一轮，直到跑满 rounds 轮。
产出：修订终稿 + 完整讨论记录（data/output/ 下两份文件）。
"""
import json
import os
from datetime import datetime

from llm.client import LLMClient, llm_for
from llm.prompts import load_prompt
from pipeline.writer import RATING_LABELS, RATING_NOTES

# 思考强度档位 -> 请求体扩展参数（火山方舟 doubao 思考模式写法）
THINKING_EXTRA = {
    "低": {"thinking": {"type": "enabled"}},
    "中": {"thinking": {"type": "enabled"}},
    "高": {"thinking": {"type": "enabled"}},
}
THINKING_NOTE = {
    "低": "（思考强度：低——请简明聚焦，直接给结论。）",
    "中": "（思考强度：中——请仔细权衡多个角度后再落笔。）",
    "高": "（思考强度：高——请先在心里做多角度深入分析、自我质疑一轮，再落笔。）",
}
DEFAULT_LEVEL = "中"


def _member_llm(llm, member, default_model, providers=None):
    """成员用专属模型时派生独立客户端（支持「提供商/模型」跨家）；主模型时复用传入实例。"""
    model = (member.get("model") or "").strip()
    if not model or model == default_model:
        return llm
    return llm_for(model, llm, providers)


def _extra_for(member):
    return THINKING_EXTRA.get((member.get("thinking") or "").strip())


def _thinking_note(member):
    lv = (member.get("thinking") or "").strip()
    return THINKING_NOTE.get(lv, "")


def _prev_reviews_text(reviews):
    if not reviews:
        return "（你是本轮第一位发言的成员）"
    return "\n\n".join(f"【{r['name']}】\n{r['review']}" for r in reviews)


def run_team_refine(idea, draft, cfg, llm, ctx, style_skill="", rating="r12",
                    force_model=None):
    """ctx 需含：target_type/cp_combo/ending_text/type_hint/knowledge/knowledge_source/personas_text。

    force_model 非空时（分级达标的自动切换），全员与主笔都改用该模型。
    返回 (final_text, transcript_text, meta)。
    """
    tcfg = cfg.get("team", {}) if isinstance(cfg, dict) else {}
    providers = cfg.get("providers") if isinstance(cfg, dict) else None
    rounds = max(1, int(tcfg.get("rounds", 1) or 1))   # 默认与 config_schema 一致
    agents = tcfg.get("agents") or []
    if not agents:
        raise SystemExit("还没有配置团队成员：请在 config.yaml 的 team.agents 或 GUI 设置页添加。")
    default_model = os.getenv("LLM_MODEL", "")
    editor_model = (tcfg.get("editor_model") or "").strip() or default_model
    llm = llm or LLMClient()

    transcript = [
        "# 团队润色讨论记录",
        "",
        f"- 时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 分级：{RATING_LABELS.get(rating, rating)}" if rating else "",
        f"- 模型切换：全员改用 {force_model}" if force_model else "",
        f"- 轮数：{rounds}｜成员：" + "、".join(
            f"{a.get('name', '?')}（{(a.get('model') or '主模型')}｜思考{a.get('thinking') or '关'}）"
            for a in agents),
        f"- 主笔：{'主模型' if editor_model == default_model else editor_model}",
        "",
    ]
    work = draft
    for rnd in range(1, rounds + 1):
        reviews = []
        for member in agents:
            name = (member.get("name") or "成员").strip()
            print(f"  [第{rnd}轮] {name} 评审中…")
            user = load_prompt(
                "team_review",
                member=name, round=str(rnd), perspective=member.get("perspective", ""),
                thinking_note=_thinking_note(member),
                prev=_prev_reviews_text(reviews),
                idea=idea or "（无）", article=work,
                knowledge=ctx["knowledge"], personas=ctx["personas_text"],
                style_skill=style_skill,
                rating_note=RATING_NOTES.get(rating, ""),
            )
            agent_llm = llm_for(force_model, llm, providers) if force_model \
                else _member_llm(llm, member, default_model, providers)
            review = agent_llm.chat(
                system="你是润色团队里的一位资深编辑。只输出你的评审意见，不要改写全文。",
                user=user, temperature=0.4, timeout=300, retries=2,
                extra_body=_extra_for(member),
            ).strip()
            reviews.append({"name": name, "review": review})
            transcript += [f"## 第 {rnd} 轮 · {name} 评审", "", review, ""]
            print(f"  [第{rnd}轮] {name} 意见已记录（约 {len(review)} 字）")

        print(f"  [第{rnd}轮] 主笔汇总修订中…")
        rev_user = load_prompt(
            "team_revise",
            round=str(rnd), idea=idea or "（无）", article=work,
            reviews=json.dumps(reviews, ensure_ascii=False, indent=1),
            knowledge=ctx["knowledge"], personas=ctx["personas_text"],
            knowledge_source=ctx["knowledge_source"],
            target_type=ctx["target_type"], cp_combo=ctx["cp_combo"],
            ending_text=ctx["ending_text"], type_hint=ctx["type_hint"],
            style_skill=style_skill,
            rating_note=RATING_NOTES.get(rating, ""),
        )
        editor = llm_for(force_model, llm, providers) if force_model \
            else _member_llm(llm, {"model": editor_model}, default_model, providers)
        work = editor.chat(
            system="你是润色团队的主笔。只输出修订后的完整文章正文（含标题），"
                   "不要输出修改说明或评审意见。",
            user=rev_user, temperature=0.6, timeout=300, retries=2,
        ).strip()
        transcript += [f"## 第 {rnd} 轮 · 主笔修订稿", "", work, ""]
        print(f"  [第{rnd}轮] 修订完成（约 {len(work)} 字）")

    return work, "\n".join(transcript), {"editor_model": editor_model}

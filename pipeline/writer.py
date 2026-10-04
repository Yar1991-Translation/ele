"""写作：目标类型 + 写作方式（自动生成/我自己写/润色/扩充）-> data/output/。

四种写作方式共用同一套分类知识库（按「文章类型·CP组合」取用，带回退链）：
- auto    自动生成：想法 + 知识库 -> 分章大纲 -> 逐章生成；
- self    我自己写：不做任何 LLM 处理，直接把原稿收进 data/output/；
- polish  润色：保留情节与结构，只按文风知识库改进语言，长稿自动分段处理；
- expand  扩充：以原稿情节为准拆成大纲，逐章扩写到目标篇幅，情节与结局不可改动。

本地人物卡（data/personas/）为最高优先级设定；想法/原稿里可用 @角色名 点名
（可带出场比例，如 @沈回:微量），点名后只读被点中的人物卡，并按点名处的
剧情定制该角色的出场与刻画。

「想法 -> 成文」的对齐链路（自动生成/扩充）：
  想法 --拆解--> 需求清单 --（可向用户提问澄清）--> 故事骨架 --covers 分配--> 分章大纲
      --（可就关键细节提问）--> 逐章落实 --> 末章统筹 --> 结局校验 --> 想法兑现清单（文首逐条验收）。
提问机制见 pipeline/ask_user.py：GUI 走任务条问答，命令行走 stdin，无人值守按建议继续。
"""
import json
import math
import os
import re
from datetime import datetime

from llm.client import LLMClient, llm_for
from llm.prompts import load_prompt, load_style_skill
from pipeline import lore
from pipeline.ask_user import AskSession
from spider import storage
from spider.models import ARTICLE_TYPES, CP_COMBOS, category_of

KNOWLEDGE_FILES = {
    "characters": "人设与关系.md",
    "style": "文风.md",
    "tropes": "桥段与爽点.md",
    "warnings": "雷点.md",
}

MODES = {"auto": "自动生成", "self": "我自己写", "polish": "润色",
         "expand": "扩充", "team": "团队润色", "quick": "关键词速写"}

# 内容分级：注入所有产出/审校正文的调用，作为硬性内容边界（默认最严的 R12）
RATINGS = ("r12", "r16", "r18", "r18g")
RATING_LABELS = {"r12": "R12（普遍级）", "r16": "R16（辅导级）",
                 "r18": "R18（无限制）", "r18g": "R18G（无限制·残酷描写）"}
RATING_NOTES = {
    "r12": "R12（普遍级·全年龄）。不出现露骨性描写与性暗示，亲密止于牵手、拥抱、"
           "额头相抵；暴力与死亡可以存在，但镜头移开——写结果与余波，不写过程细节；"
           "血腥、猎奇、残酷描写一律不出现。",
    "r16": "R16（辅导级）。允许较重的暴力、死亡与心理创伤的直白描写；亲密止于"
           "接吻与相拥，性内容只作暗示或淡出转场；血腥可以有，不渲染猎奇细节。",
    "r18": "R18（限制级·无限制模式）。成人内容无限制：露骨性描写、重度暴力都可以"
           "直接、细致地写，不做淡出转场、不镜头回避，也不受「服务于情节」「不许"
           "堆砌」之类的文风约束——按作者的想法与人物关系放开写。唯一硬边界"
           "（不可覆盖）：禁止任何涉及未成年人的性内容；角色年龄存疑时一律按"
           "未成年处理、不写。",
    "r18g": "R18G（限制级·无限制模式，含残酷描写）。在 R18 无限制模式基础上，"
            "血腥、猎奇、残酷、躯体损伤与死亡过程都直白细致地写，不加回避、不做"
            "弱化。唯一硬边界（不可覆盖）：禁止任何涉及未成年人的性内容；角色"
            "年龄存疑时一律按未成年处理、不写。",
}


def resolve_rating(rating=None, cfg_write=None):
    """归一分级：CLI/GUI 传参优先，其次 config 默认值，兜底最严的 R12。"""
    cfg_write = cfg_write or {}
    r = (rating or "").strip() or (cfg_write.get("rating") or "").strip() or "r12"
    return r if r in RATINGS else "r12"


def rating_override(models_cfg, rating):
    """分级达标时的替代模型引用（如 grok/grok-4.6）；未启用或未达标返回空串。

    models_cfg 的 rating_switch = 达到该分级即切换（空=关闭），
    rating_model = 替代模型（支持「提供商/模型」语法）。
    """
    switch_at = ((models_cfg or {}).get("rating_switch") or "").strip()
    ref = ((models_cfg or {}).get("rating_model") or "").strip()
    if switch_at in RATINGS and ref and rating in RATINGS \
            and RATINGS.index(rating) >= RATINGS.index(switch_at):
        return ref
    return ""

# 人物卡来源（运行页可选）：both=官方+蒸馏结合 / distilled=仅蒸馏卡 / official=仅官方卡
PERSONA_SOURCES = {"both": "两者结合", "distilled": "仅蒸馏卡", "official": "仅官方卡"}


def source_mode_name(m):
    return PERSONA_SOURCES.get(m, PERSONA_SOURCES["both"])

# 单人向的硬性规则：CP组合强制微量
RULE_HINTS = {
    "单人向": "文章类型是单人向：聚焦单一角色的人物侧写/心境/成长，"
              "CP组合为微量——感情戏只能作为极轻的点缀或背景，绝不能成为主线。",
    "CP向": "文章类型是CP向：以感情线为核心主线，按指定的 CP 组合展开。",
    "其他": "文章类型是其他：剧情向/日常向/世界观向为主，感情线可有可无。",
}

POLISH_SINGLE_LIMIT = 12000   # 原稿不超过该字数时一次润色完
POLISH_CHUNK = 6000           # 长稿分段润色的每段上限
DRAFT_INPUT_LIMIT = 20000     # 喂给 LLM 的原稿上限（扩充/逐章参照用）

# @ 点名：@角色名 或 @角色名:出场比例（冒号/全角括号两种写法都支持，比例可省略）
_MENTION_RE = re.compile(
    r"@([^\s@，。；！？、：:（）()【】\[\]「」『』'\"”’]{1,30})"
    r"(?:[:：]\s*([^\s@，。；！？、（）()【】\[\]]{1,6})"
    r"|（\s*([^\s@，。；！？、：:（）()【】\[\]]{1,6})\s*）)?")

# 出场比例档位（从低到高）；未标注默认"配角"，未知档位按原文透传给模型
APPEARANCE_LEVELS = ["跑龙套", "微量", "配角", "重要", "主役"]
MAIN_LEVEL = "主役"   # 主角档：双卡体系只对主角生效
LEVEL_HINTS = {
    "跑龙套": "一两个镜头带过，不参与主线",
    "微量": "少量点缀，一两处短出场",
    "配角": "有明确戏份，但不占主线",
    "重要": "关键配角，多条剧情线都有参与",
    "主役": "核心主角，几乎贯穿全程",
}


def resolve_target(article_type=None, cp_combo=None, ending=None, cfg_write=None):
    """归一写作目标：CLI/GUI 传参优先，其次 config 默认值；单人向强制微量。"""
    cfg_write = cfg_write or {}
    t = (article_type or cfg_write.get("article_type") or "CP向").strip()
    c = (cp_combo or cfg_write.get("cp_combo") or "男男").strip()
    e = (ending if ending is not None and str(ending).strip() != ""
         else cfg_write.get("ending") or "不限").strip()
    if t not in ARTICLE_TYPES:
        t = "CP向"
    if c not in CP_COMBOS:
        c = "男男"
    if t == "单人向":
        c = "微量"
    if e not in ("HE", "BE", "开放式", "不限"):
        e = "不限"
    return t, c, e


def _all_personas(cfg_write):
    """全部本地人设（use_personas 关闭时为空）。"""
    if not cfg_write.get("use_personas", True):
        return []
    limit = int(cfg_write.get("persona_char_limit", 4000))
    out = []
    for p in storage.parse_personas():
        content = p["content"]
        if len(content) > limit:
            content = content[:limit] + "\n<!-- （超长截断） -->"
        out.append({**p, "content": content})
    return out


def _load_distilled_cards(cfg_write):
    """全部蒸馏人物卡（data/personas_distilled/，来自同人文深度蒸馏）。"""
    if not cfg_write.get("use_personas", True):
        return []
    limit = int(cfg_write.get("persona_char_limit", 4000))
    out = []
    for p in storage.load_distilled_cards():
        content = p["content"]
        if len(content) > limit:
            content = content[:limit] + "\n<!-- （超长截断） -->"
        out.append({**p, "content": content})
    return out


def _extract_mentions(*texts):
    """提取 @角色名（可带 :比例 或 （比例）），按出现顺序去重（同角色取最高档）。"""
    order, levels = [], {}
    for t in texts:
        if not t:
            continue
        for m, l1, l2 in _MENTION_RE.findall(t):
            level = (l1 or l2 or "").strip()
            if m not in levels:
                order.append(m)
                levels[m] = level
            elif level:
                prev = levels[m]
                if prev not in APPEARANCE_LEVELS or (
                        level in APPEARANCE_LEVELS and
                        APPEARANCE_LEVELS.index(level) > APPEARANCE_LEVELS.index(prev)):
                    levels[m] = level
    return [{"name": m, "level": levels[m] or None} for m in order]


def _match_mentions(mentions, personas):
    """@ 点名匹配：精确同名优先，其次包含关系（@沈 能匹配 沈回）。

    返回 (被选中的人设列表, 未匹配的 @ 名单)。没有 @ 时全部人设生效。
    """
    if not mentions:
        return list(personas), []
    selected, unmatched = [], []
    for m in mentions:
        if any(p["name"] == m["name"] and p in selected for p in personas):
            continue
        exact = [p for p in personas if p["name"] == m["name"]]
        if exact:
            selected += exact
            continue
        partial = [p for p in personas if m["name"] in p["name"] or p["name"] in m["name"]]
        if partial:
            partial.sort(key=lambda p: len(p["name"]))
            selected.append(partial[0])
        else:
            unmatched.append(m["name"])
    uniq, seen = [], set()
    for p in selected:
        if p["name"] not in seen:
            seen.add(p["name"])
            uniq.append(p)
    return uniq, unmatched


def _mention_contexts(mentions, *texts):
    """提取每个 @ 点名所在的小句，作为该角色的剧情定制要求。"""
    ctx = {m["name"]: [] for m in mentions}
    for t in texts:
        if not t:
            continue
        for frag in filter(str.strip, re.split(r"(?<=[，。；！？!?;,\n])", t)):
            for name in ctx:
                if "@" + name in frag and frag.strip() not in ctx[name]:
                    ctx[name].append(frag.strip())
    return ctx


def _pick_persona(pool, name):
    """在单个人设池里点名：精确同名优先，其次包含关系。"""
    exact = [p for p in pool if p["name"] == name]
    if exact:
        return exact[0]
    partial = sorted([p for p in pool if name in p["name"] or p["name"] in name],
                     key=lambda p: len(p["name"]))
    return partial[0] if partial else None


def _select_dual(mentions, all_official, all_distilled, source_mode,
                 gti_official_only=True):
    """双池点名选择。返回 (官方选中, 蒸馏选中, 未匹配名单)。

    没有任何 @ 时按来源全量生效。同一次点名可在两层各命中一张卡
    （同角色官方+蒸馏并存正是双卡体系的设计意图）。

    gti_official_only（两者结合模式下生效）：只有主角档（主役）才注入蒸馏层，
    其余干员一律只用官方卡——配角/跑龙套的同人二设不进正文。
    """
    use_off = source_mode in ("both", "official")
    use_dis = source_mode in ("both", "distilled")
    main_only = gti_official_only and source_mode == "both"
    if not mentions:
        return (list(all_official) if use_off else [],
                list(all_distilled) if use_dis else [], [])
    sel_off, sel_dis, unmatched = [], [], []
    seen = set()

    def add_unique(lst, p):
        if p and all(x["name"] != p["name"] for x in lst):
            lst.append(p)

    for m in mentions:
        n = m["name"]
        if n in seen:
            continue
        seen.add(n)
        off = _pick_persona(all_official, n) if use_off else None
        keep_dis = use_dis and (not main_only or m["level"] == MAIN_LEVEL)
        dis = _pick_persona(all_distilled, n) if keep_dis else None
        if off is None and dis is None:
            unmatched.append(n)
            continue
        add_unique(sel_off, off)
        add_unique(sel_dis, dis)
    return sel_off, sel_dis, unmatched


# 非角色卡（症状卡/设定集一类）不进阵容名单
_NON_CHARACTER_SUFFIX = ("状况卡", "设定集", "世界书", "背景集", "写作准则")


def _is_character_card(p):
    hay = (p.get("name") or "") + (p.get("file") or "")
    return not hay.endswith(_NON_CHARACTER_SUFFIX) and not any(
        s in hay for s in _NON_CHARACTER_SUFFIX)


def _roster_note(all_official):
    """阵容规定：出场干员只允许取自官方人物卡名单。"""
    names = [p["name"] for p in all_official if _is_character_card(p)]
    if not names:
        return ""
    return ("【阵容规定 · 硬性】本作允许出场的 GTI 干员仅限以下官方档案名单内的角色：\n"
            + "、".join(names)
            + "\n名单外不得虚构、引入或改名任何干员。名单内角色除主角（主役）外"
              "一律以官方档案为准，不得套用同人二设。")


def _build_quick_idea(keyword, roster_all, all_official):
    """快速模式：关键词 + 已点名角色 + 可选全员登场 -> 构建给管道的想法文本。

    关键词只是题眼：剧情走向、结构、结局细节交给骨架/大纲结合知识库自行设计，
    关键分歧走现有提问机制。全员登场时其余干员以跑龙套点名注入（与已点名的
    去重），并附阵容规定（名单外不得虚构）。返回的新想法文本会重新过点名解析，
    所以全员角色的人物卡会被正常注入。
    """
    kw = (keyword or "").strip()
    parts = ["【主题关键词】" + (kw or "（未提供，按知识库自由发挥）"),
             "（轻量输入：上面的关键词是主题/题眼，不是完整情节。剧情走向、结构与"
             "结局细节由你结合知识库自行设计；有拿不准的分歧按流程向我提问。）"]
    if roster_all:
        mentioned = {m["name"] for m in _extract_mentions(kw, "")}
        roster = ["@" + p["name"] + ":跑龙套" for p in all_official
                  if _is_character_card(p) and p["name"] not in mentioned]
        if roster:
            parts.append("全员登场（每人一两个镜头、一两句台词，不许抢主线、"
                         "不许扎堆出场）：\n" + "  ".join(roster))
        note = _roster_note(all_official)
        if note:
            parts.append(note)
    return "\n\n".join(parts)


# 低档位点名只截取卡片前段：跑龙套/微量不需要整份档案
LEVEL_CHAR_LIMIT = {"跑龙套": 800, "微量": 1500}


def _block_for(p, ctx_by_mention, level_by_name):
    level = level_by_name.get(p["name"]) or "配角"
    content = p["content"]
    cap = LEVEL_CHAR_LIMIT.get(level)
    if cap and len(content) > cap:
        content = content[:cap] + "\n<!-- （出场比例低，档案已截断） -->"
    block = f"=== {p['name']} ===\n{content}"
    hint = LEVEL_HINTS.get(level, "自定义出场比例")
    block += f"\n（出场比例：{level}——{hint}）"
    notes = []
    for m, frags in ctx_by_mention.items():
        if frags and (m == p["name"] or m in p["name"] or p["name"] in m):
            notes += frags
    if notes:
        block += "\n（用户点名此角色时的剧情要求：" + "；".join(dict.fromkeys(notes)) + "）"
    return block


def _weight_note(official_weight):
    w = max(0, min(100, int(official_weight or 30)))
    d = 100 - w
    if w >= 70:
        tone = "官方档案层主导：人物塑造以官方设定为骨架，蒸馏层仅补充同人语境的细节"
    elif w <= 30:
        tone = "同人蒸馏层主导：人物塑造以蒸馏卡为骨架，官方层仅校正事实"
    else:
        tone = "两层均衡互校：塑造细节以蒸馏层为主，关键事实以官方层为准"
    return w, d, tone


def _build_dual_personas(sel_off, sel_dis, ctx_by_mention, level_by_name,
                         source_mode, official_weight):
    """按来源与权重组装人物卡文本。返回 (personas_text, info_line)。"""
    w, d, tone = _weight_note(official_weight)
    sections = []
    if sel_off:
        sections.append((w, "官方档案层 · 事实边界",
            "仅在与情节直接相关时作为事实依据；禁止在正文罗列档案资料"
            "（生日/身高/代号/配音等一律不得复述）。", sel_off))
    if sel_dis:
        sections.append((d, "同人蒸馏层 · 塑造依据",
            "同人语境下的形象（含圈内自设倾向），是人物塑造的主要参照。", sel_dis))
    sections.sort(key=lambda x: -x[0])   # 权重高的层放前面

    parts = []
    if len(sections) == 2:
        parts.append(f"【人物资料 · 双层体系】官方档案 {w}% ｜ 同人蒸馏 {d}%。{tone}。"
                     "两层冲突时：塑造以权重高者为主导，另一层仅校正事实。")
    for weight, title, rule, lst in sections:
        parts.append(f"【{title}】（权重 {weight}%）{rule}")
        parts += [_block_for(p, ctx_by_mention, level_by_name) for p in lst]
    info = "、".join(f"{t}×{len(l)}" for _, t, _, l in sections) or "无"
    return "\n\n".join(parts), info


def _load_knowledge(category, limit):
    """加载分类知识库，带回退链：精确分类 -> 同文章类型 -> 全部。

    返回 (拼接文本, 来源说明)。
    """
    root = storage.KNOWLEDGE_DIR
    cats = sorted(d for d in os.listdir(root)
                  if os.path.isdir(os.path.join(root, d))) if os.path.isdir(root) else []
    if not cats:
        return "", "（knowledge 目录为空）"
    if category in cats:
        chosen, source = [category], f"精确匹配：{category}"
    else:
        same_type = [c for c in cats if c == category.split("·")[0] or
                     c.startswith(category.split("·")[0] + "·")]
        if same_type:
            chosen, source = same_type, f"同类型合并（{category} 的专属知识库尚未蒸馏）"
        else:
            chosen, source = cats, f"全部混合（{category} 的专属知识库尚未蒸馏，请以目标类型为准取舍）"

    parts = []
    for cat in chosen:
        for key, fname in KNOWLEDGE_FILES.items():
            path = os.path.join(storage.knowledge_dir(cat), fname)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                continue
            if len(text) > limit:
                text = text[:limit] + "\n<!-- （超长截断） -->"
            parts.append(f"=== {cat} · {fname[:-3]} ===\n{text}")
    return "\n\n".join(parts), source


def _sanitize_filename(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", s).strip()
    return s[:60] or "未命名"


def _wc(t):
    """正文有效字数（去空白），体量校准统一用它。"""
    return len(re.sub(r"\s", "", t or ""))


def _ending_window(body, head=4000, tail=16000):
    """结局校验的取文窗口。长文必须带上真正的结尾——
    早先只取前 24000 字，篇幅一长校验看到的全是开头，结局根本不在窗口里。"""
    if len(body) <= head + tail:
        return body
    return body[:head] + "\n\n[……中段略……]\n\n" + body[-tail:]


def _story_map(chapters_spec, current_idx):
    """全篇章节表：已完成的即前情，待写的供埋线与衔接（取自大纲，零额外开销）。"""
    lines = []
    for i, ch in enumerate(chapters_spec, 1):
        if i == current_idx:
            mark = "【正在写这章】"
        elif i < current_idx:
            mark = "【已写完】"
        else:
            mark = "【待写】"
        summary = re.sub(r"\s+", " ", str(ch.get("summary") or "")).strip()
        lines.append("第 {} 章《{}》{}：{}".format(
            i, ch.get("title") or f"第{i}章", mark, summary))
    return "\n".join(lines)


def _cap_bible(lines, keep_head=25, keep_tail=75):
    """连续性档案防膨胀：保留开局设定与最近事实，中间折叠。"""
    if len(lines) <= keep_head + keep_tail + 1:
        return lines
    dropped = len(lines) - keep_head - keep_tail
    return (lines[:keep_head]
            + ["……（中间 {} 条较早事实已折叠）……".format(dropped)]
            + lines[-keep_tail:])


def _assemble_body(chapters_spec, chapter_texts):
    body_parts = []
    for i, (ch, text) in enumerate(zip(chapters_spec, chapter_texts), 1):
        ch_title = str(ch.get("title") or f"第{i}章")
        if len(chapters_spec) > 1:
            body_parts.append(f"## {ch_title}\n\n{text}\n")
        else:
            body_parts.append(text + "\n")
    return "\n".join(body_parts)


# 需求清单的分类（write_requirements.md 的口径）
_REQ_KINDS = ("情节", "基调", "禁忌", "其他")


def _extract_requirements(llm, idea, target_type, type_hint):
    """把自由文本想法拆成结构化需求清单（忠实复述，不脑补）。

    这是「想法 -> 成文」的契约层：拆出来的清单会注入骨架/大纲/逐章/自查，
    并在成文后逐条验收。拆解失败退化为整段想法一条，绝不阻塞写作。
    """
    if not (idea or "").strip():
        return []
    try:
        raw = llm.chat_json(
            system="你是需求分析师。只输出 JSON。",
            user=load_prompt("write_requirements", idea=idea,
                             target_type=target_type, type_hint=type_hint),
            temperature=0.2, timeout=120, retries=1,
        )
        items = []
        for it in (raw.get("items") or []) if isinstance(raw, dict) else []:
            req = str(it.get("req") or "").strip()
            if not req:
                continue
            kind = str(it.get("kind") or "").strip()
            items.append({"id": len(items) + 1,
                          "kind": kind if kind in _REQ_KINDS else "其他",
                          "req": req})
        return items
    except Exception as e:  # noqa: BLE001 拆解失败不阻塞
        print("  想法拆解失败，按原文整段作为一条需求：{}".format(str(e)[:80]))
        return [{"id": 1, "kind": "情节", "req": (idea or "").strip()[:200]}]


def _requirements_text(items):
    """需求清单渲染成各阶段提示词共用的块。"""
    if not items:
        return "（用户没写具体要求，按目标类型自由发挥）"
    lines = ["【用户需求清单】（全部必须兑现；「情节」类要落实为具体场景；"
             "编号供章节分配（covers）引用）"]
    for it in items:
        lines.append("{}. [{}] {}".format(it["id"], it["kind"], it["req"]))
    return "\n".join(lines)


def _idea_note_text(by_id, verdict):
    """文首「想法兑现清单」块：逐条 ✓/✗，让用户一眼看到想法落到文里没有。"""
    rows = []
    for r in (verdict.get("items") or []):
        try:
            rid = int(r.get("id"))
        except (TypeError, ValueError):
            continue
        if rid not in by_id:
            continue
        rows.append((by_id[rid], bool(r.get("hit")), str(r.get("note") or "").strip()))
    if not rows:
        return ""
    lines = ["> **想法兑现清单**（AI 逐条自查，供参考）："]
    for it, hit, note in rows:
        tail = ("——" + note) if note and not hit else ""
        lines.append("> - {} [{}] {}{}".format(
            "✓" if hit else "✗", it["kind"], it["req"], tail))
    summary = str(verdict.get("summary") or "").strip()
    if summary:
        lines.append("> 总评：{}".format(summary))
    return "\n".join(lines) + "\n\n"


def _gen_questions(llm, stage_label, idea, requirements, plan, max_n):
    """让模型决定有哪些「不问会写偏」的问题；没有就返回空（大多数时候该是空）。"""
    if max_n <= 0:
        return []
    try:
        raw = llm.chat_json(
            system="你是提问策略师。只输出 JSON。",
            user=load_prompt("write_questions", stage_label=stage_label,
                             idea=idea or "（无）", requirements=requirements,
                             plan=plan or "（本阶段暂无大纲）",
                             max_questions=str(max_n)),
            temperature=0.3, timeout=90, retries=1,
        )
        qs = []
        for q in (raw.get("questions") or []) if isinstance(raw, dict) else []:
            text = str(q.get("q") or "").strip()
            if not text:
                continue
            opts = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
            qs.append({"q": text, "options": opts[:4],
                       "suggest": str(q.get("suggest") or "").strip()})
            if len(qs) >= max_n:
                break
        return qs
    except Exception as e:  # noqa: BLE001 提问失败不阻塞写作
        print("  提问生成失败，跳过提问：{}".format(str(e)[:80]))
        return []


def _qa_note_text(qa_log):
    """文首「创作问答」记录：让用户看到写作中问过什么、拿的是谁的答案。"""
    if not qa_log:
        return ""
    lines = ["> **创作问答**（写作过程中确认过的问题）："]
    for q, a, src in qa_log:
        lines.append("> - {} —— {}（{}）".format(q, a, src))
    return "\n".join(lines) + "\n\n"


def _split_chunks(text, limit=POLISH_CHUNK):
    """按段落把长稿切成润色分段；单段超过上限时硬切，尽量不丢衔接。"""
    chunks, cur, cur_len = [], [], 0

    def flush():
        nonlocal cur, cur_len
        if cur:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0

    for line in text.split("\n"):
        while len(line) > limit:  # 超长单段硬切
            flush()
            chunks.append(line[:limit])
            line = line[limit:]
        if cur and cur_len + len(line) > limit:
            flush()
        cur.append(line)
        cur_len += len(line)
    flush()
    return chunks


def _output_path(title):
    os.makedirs(storage.OUTPUT_DIR, exist_ok=True)
    fname = "{}_{}.md".format(datetime.now().strftime("%Y%m%d-%H%M%S"), _sanitize_filename(title))
    return os.path.join(storage.OUTPUT_DIR, fname)


def _header(title, length_note, category, ending_text, mode_name, knowledge_source,
            idea, rating_label=""):
    rating_part = f" ｜ 分级：{rating_label}" if rating_label else ""
    return (
        f"# {title}\n\n"
        f"> 由蒸馏创作管道保存于 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"> {length_note}｜ 类型：{category} ｜ {ending_text} ｜ 写作方式：{mode_name}"
        f"{rating_part}\n"
        f"> 知识库来源：{knowledge_source}\n\n"
        + (f"**我的想法**：{idea}\n\n---\n\n" if idea else "")
    )


def _story_so_far(chapters_spec, chapter_texts, limit=160):
    """全文脉络摘要：每章的标题 + 首尾片段，供终局统筹把握全局。"""
    lines = []
    for i, (ch, text) in enumerate(zip(chapters_spec, chapter_texts), 1):
        clean = re.sub(r"\s+", " ", text).strip()
        head, tail = clean[:limit], clean[-limit:] if len(clean) > limit else ""
        lines.append("第 {} 章《{}》（约 {} 字）\n  开头：{}\n  结尾：{}".format(
            i, ch.get("title") or f"第{i}章", len(re.sub(r"\s", "", clean)),
            head, tail if tail else head))
    return "\n".join(lines)


def _save_self(idea, draft, article_type, cp_combo, ending, rating_label=""):
    """我自己写：不做 LLM 处理，原稿直接收进 data/output/。"""
    category = category_of(article_type, cp_combo)
    ending_text = "结局不限" if ending == "不限" else f"结局走向：{ending}"
    lines = draft.splitlines()
    has_h1 = any(l.startswith("# ") for l in lines)
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
    title = title or (idea or "").strip()[:40] or "未命名"
    body = re.sub(r"^#\s+.*\n", "", draft, count=1).strip() if has_h1 else draft.strip()
    path = _output_path(title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_header(title, "", category, ending_text, MODES["self"],
                        "（原稿，未经 LLM 处理）", idea, rating_label) + body + "\n")
    print("已保存你的原稿 -> {}".format(path))
    return path


def _polish(llm, idea, draft, knowledge, article_type, cp_combo, ending,
            personas_text="", style_skill="", rating="r12"):
    """润色：保留情节与结构，按文风知识库改进语言。长稿分段处理保持衔接。"""
    ending_text = "结局不限" if ending == "不限" else f"结局走向：{ending}"
    ctx = dict(target_type=article_type, cp_combo=cp_combo, ending_text=ending_text,
               type_hint=RULE_HINTS[article_type], knowledge=knowledge, idea=idea or "（无）",
               personas=personas_text, rating_note=RATING_NOTES.get(rating, ""))
    if len(draft) <= POLISH_SINGLE_LIMIT:
        chunks = [draft]
    else:
        chunks = _split_chunks(draft)
        print("原稿较长，分 {} 段依次润色".format(len(chunks)))
    polished = []
    for i, chunk in enumerate(chunks, 1):
        user = load_prompt("polish", draft=chunk,
                           prev_tail=polished[-1][-600:] if polished else "（这是开头）",
                           part_note=f"（第 {i}/{len(chunks)} 段）" if len(chunks) > 1 else "",
                           style_skill=style_skill,
                           **ctx)
        text = llm.chat(
            system="你是文笔出色的同人编辑。只输出润色后的正文，不要任何解释、标题或作者的话。",
            user=user, temperature=0.5,
        ).strip()
        polished.append(text)
        print("  润色进度 {}/{}（约 {} 字）".format(i, len(chunks), len(text)))
    full = "\n\n".join(polished)
    title = next((l[2:].strip() for l in draft.splitlines() if l.startswith("# ")), "") or "润色稿"
    path = _output_path(title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_header(title, f"原文约 {len(draft)} 字 -> 润色后约 {len(full)} 字 ｜ ",
                        category_of(article_type, cp_combo), ending_text, MODES["polish"],
                        "文风按知识库调整，情节未改动", idea, RATING_LABELS.get(rating, ""))
                + full + "\n")
    print("润色完成：原文约 {} 字 -> 约 {} 字 -> {}".format(len(draft), len(full), path))
    return path


def _team_polish(idea, draft, cfg, llm, article_type, cp_combo, ending,
                 personas_text, knowledge, knowledge_source, style_skill="",
                 rating="r12", force_model=None):
    """团队润色：多模型/多视角评审讨论，多轮修订。输出终稿 + 讨论记录。"""
    from pipeline.team_refine import run_team_refine
    category = category_of(article_type, cp_combo)
    ending_text = "结局不限" if ending == "不限" else f"结局走向：{ending}"
    ctx = dict(target_type=article_type, cp_combo=cp_combo, ending_text=ending_text,
               type_hint=RULE_HINTS[article_type], knowledge=knowledge,
               knowledge_source=knowledge_source, personas_text=personas_text)
    work, transcript, meta = run_team_refine(idea, draft, cfg, llm, ctx,
                                             style_skill=style_skill, rating=rating,
                                             force_model=force_model)

    lines = work.splitlines()
    has_h1 = any(l.startswith("# ") for l in lines)
    title = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
    title = title or (idea or "").strip()[:40] or "团队润色稿"
    body = re.sub(r"^#\s+.*\n", "", work, count=1).strip() if has_h1 else work.strip()

    path = _output_path(title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_header(title, f"原稿约 {len(draft)} 字 -> 终稿约 {len(body)} 字 ｜ ",
                        category, ending_text, MODES["team"],
                        f"主笔：{meta['editor_model']}；成员意见见讨论记录", idea,
                        RATING_LABELS.get(rating, ""))
                + body + "\n")
    tpath = _output_path(title + "_讨论记录")
    with open(tpath, "w", encoding="utf-8") as f:
        f.write(transcript + "\n")
    print("团队润色完成：终稿 -> {}".format(path))
    print("讨论记录 -> {}".format(tpath))
    return path


def _gen_chapter_text(llm_client, system, user, temperature, query_rounds=0,
                      char_limit=4000, entries=None, files=None):
    """逐章生成：支持动笔前「备料」查询（设定/剧情文件与人物卡全文）。

    模型输出 JSON {"queries": [...]} 视为查询请求（见 lore.parse_queries），
    回填结果后继续；输出正文则直接返回。查询轮次用尽后强制其落笔，
    极端情况下（轮尽仍查询）再兜底一轮，整体有界。
    """
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    for round_no in range(max(0, query_rounds)):
        resp = llm_client.chat_messages(messages, temperature=temperature).strip()
        queries = lore.parse_queries(resp)
        if not queries:
            return resp
        result = lore.run_queries(queries, char_limit=char_limit,
                                  entries=entries, files=files)
        messages.append({"role": "assistant", "content": resp})
        left = query_rounds - round_no - 1
        if left <= 0:
            messages.append({"role": "user", "content":
                             "查询机会已用完。以下是最后一批查询结果：\n\n"
                             + (result or "（没有查到内容）")
                             + "\n\n请立即输出本章正文，不要再输出查询 JSON。"})
        elif result:
            print("  备料查询 {} 条，已回填（还剩 {} 轮）".format(len(queries), left))
            messages.append({"role": "user", "content": "查询结果：\n\n" + result
                             + "\n\n现在继续：资料够就直接输出本章正文；"
                               "还需要查别的可再输出查询 JSON。"})
        else:
            print("  查询没有命中可用资料（还剩 {} 轮）".format(left))
            messages.append({"role": "user", "content":
                             "这些查询没有查到内容（名字要与索引一致）。"
                             "请直接输出本章正文，或换准确的名字再查一次。"})
    resp = llm_client.chat_messages(messages, temperature=temperature).strip()
    queries = lore.parse_queries(resp)
    if queries:   # 轮尽仍在查询：兜底一轮，整体有界
        result = lore.run_queries(queries, char_limit=char_limit,
                                  entries=entries, files=files)
        resp = llm_client.chat_messages(
            messages + [{"role": "assistant", "content": resp},
                        {"role": "user", "content":
                         "查询结果：\n\n" + (result or "（没有查到内容）")
                         + "\n\n这是最后一次交互，现在必须直接输出本章正文。"}],
            temperature=temperature).strip()
    return resp


def write_article(idea, cfg, llm=None, article_type=None, cp_combo=None, ending=None,
                  mode="auto", draft="", persona_source=None, official_weight=None,
                  roster_all=None, rating=None):
    wcfg = cfg.get("write", {})
    length = int(wcfg.get("length", 8000))
    chapter_chars = int(wcfg.get("chapter_chars", 2500))
    temperature = float(wcfg.get("temperature", 0.8))
    knowledge_limit = int(wcfg.get("knowledge_char_limit", 6000))

    mode = mode if mode in MODES else "auto"
    # 快速模式复用 auto 全流程，只替换想法文本与方式名
    quick_used = mode == "quick"
    if quick_used:
        mode = "auto"
    mode_label = "关键词速写" if quick_used else MODES[mode]
    source_mode = persona_source if persona_source in PERSONA_SOURCES else \
        (wcfg.get("persona_source") or "both")
    official_weight = int(official_weight) if official_weight is not None else \
        int(wcfg.get("official_weight", 30) or 30)
    article_type, cp_combo, ending = resolve_target(article_type, cp_combo, ending, wcfg)
    rating = resolve_rating(rating, wcfg)
    rating_note = RATING_NOTES[rating]
    rating_label = RATING_LABELS[rating]
    category = category_of(article_type, cp_combo)
    ending_text = "结局不限" if ending == "不限" else f"结局走向：{ending}"

    if mode == "self":
        return _save_self(idea, draft, article_type, cp_combo, ending,
                          rating_label=rating_label)

    if mode != "auto" and not (draft or "").strip():
        raise SystemExit("「{}」方式需要原稿：CLI 用 --file/--draft，GUI 粘贴到原稿框".format(MODES[mode]))

    # 人物卡：双池（官方/手写 + 蒸馏）+ @ 点名 + 来源与权重
    all_official = _all_personas(wcfg)
    all_distilled = _load_distilled_cards(wcfg)
    gti_only = bool(wcfg.get("gti_official_only", True))
    if quick_used:
        idea = _build_quick_idea(idea, roster_all, all_official)
    mentions = _extract_mentions(idea, draft)
    sel_off, sel_dis, unmatched = _select_dual(
        mentions, all_official, all_distilled, source_mode, gti_only)
    level_by_name = {m["name"]: m["level"] for m in mentions if m["level"]}
    personas_text, persona_info = _build_dual_personas(
        sel_off, sel_dis, _mention_contexts(mentions, idea, draft),
        level_by_name, source_mode, official_weight)
    if gti_only:
        roster = _roster_note(all_official)
        if roster:
            personas_text = (personas_text + "\n\n" + roster) if personas_text else roster
    persona_names = [p["name"] for p in sel_off] + [p["name"] for p in sel_dis]

    knowledge, knowledge_source = _load_knowledge(category, knowledge_limit)
    if not knowledge and not personas_text:
        raise SystemExit(
            f"data/knowledge/ 下还没有「{category}」的分类知识库，"
            "也没有导入任何人设。请先 python main.py distill，"
            "或把人设 .md/.txt 放进 data/personas/（GUI 数据页可上传）。")
    if not knowledge:
        knowledge_source = "（无知识库，仅凭人设写作）"
    if unmatched:
        avail = sorted({p["name"] for p in all_official} | {p["name"] for p in all_distilled})
        print("未识别的 @：{}（可用：{}）".format("、".join(unmatched), "、".join(avail) or "无"))
    print("人物卡：{}（{}）{}｜@ 点名处按剧情定制".format(
        source_mode_name(source_mode), persona_info,
        "｜配角及以下只用官方卡" if gti_only else ""))
    hollow = len(storage.distilled_card_files()) - len(all_distilled)
    if hollow > 0:
        print("（{} 张空壳蒸馏卡已忽略，这些角色回落官方卡）".format(hollow))
    print(f"写作目标：{category} ｜ {ending_text} ｜ 方式：{mode_label}（知识库来源：{knowledge_source}）")
    print(f"内容分级：{rating_label}")

    llm = llm or LLMClient()
    providers = cfg.get("providers")
    models_cfg = cfg.get("models") or {}
    style_skill = load_style_skill(wcfg.get("style_skill", "精简"))
    if style_skill:
        print("去AI味规范：{}（已注入写作/修订/团队提示词）"
              .format((wcfg.get("style_skill") or "精简").strip() or "精简"))
    # 分级达标时：写作全流程改用替代模型（如 R16+ 切 Grok）
    override_ref = rating_override(models_cfg, rating)
    if override_ref:
        print("内容分级 {} 达到切换线（{} 起）：本次写作改用 {}"
              .format(RATING_LABELS[rating], models_cfg.get("rating_switch"), override_ref))

    if mode == "polish":
        polish_llm = llm_for(override_ref or models_cfg.get("polish"), llm, providers)
        return _polish(polish_llm, idea, draft, knowledge, article_type, cp_combo,
                       ending, personas_text=personas_text, style_skill=style_skill,
                       rating=rating)

    if mode == "team":
        return _team_polish(idea, draft, cfg, llm, article_type, cp_combo, ending,
                            personas_text=personas_text, knowledge=knowledge,
                            knowledge_source=knowledge_source, style_skill=style_skill,
                            rating=rating, force_model=override_ref or None)

    # ---- auto：骨架 → 大纲 → 逐章（连续性档案 + 自查修订）｜ expand：原稿定骨架 ----
    n_chapters = max(1, math.ceil(length / chapter_chars))
    self_revise = bool(wcfg.get("self_revise", True))

    outline_llm = llm_for(override_ref or models_cfg.get("write_outline"), llm, providers)
    chapter_llm = llm_for(override_ref or models_cfg.get("write_chapter"), llm, providers)
    revise_llm = llm_for(override_ref or models_cfg.get("write_revise"), llm, providers)
    bible_llm = llm_for(override_ref or models_cfg.get("bible_update"), llm, providers)
    ending_check_llm = llm_for(override_ref or models_cfg.get("ending_check"), llm, providers)
    idea_check_llm = llm_for(override_ref or models_cfg.get("idea_check"), llm, providers)
    assigned = {"大纲": outline_llm.label, "正文": chapter_llm.label,
                "自查": revise_llm.label, "档案": bible_llm.label,
                "结局校验": ending_check_llm.label, "想法校验": idea_check_llm.label}
    if len(set(assigned.values())) > 1:
        print("模型分配：" + "｜".join("{} {}".format(k, v) for k, v in assigned.items()))

    # ---- 章节查询工具：动笔前可查阅 data/lore/ 设定剧情文件与人物卡全文 ----
    query_rounds = max(0, int(wcfg.get("query_rounds", 2) or 0)) \
        if wcfg.get("query_tools", True) else 0
    query_char_limit = int(wcfg.get("query_char_limit", 4000) or 4000)
    lore_entries = lore.persona_entries() if query_rounds > 0 else []
    lore_filelist = lore.lore_files() if query_rounds > 0 else []
    lore_tools = lore.tool_instructions(
        lore.build_index(lore_entries, lore_filelist), query_rounds) \
        if query_rounds > 0 else ""
    if lore_tools:
        print("查询工具：已启用（写作时可查阅设定/剧情文件与人物卡，最多 {} 轮）"
              .format(query_rounds))

    # 想法 -> 需求清单：全文的兑现契约（骨架覆盖、大纲分配到章、逐章落实、成文验收）
    req_items = _extract_requirements(outline_llm, idea, article_type,
                                      RULE_HINTS[article_type])
    req_text = _requirements_text(req_items)

    # ---- 提问点 ①：想法澄清——歧义不问清，后面全写偏 ----
    asker = AskSession(wcfg)
    if asker.remaining:
        clarify_label = "想法澄清（动笔前）"
        if quick_used:
            clarify_label += ("——本次想法只是一个关键词：请把第一个问题设计成"
                              "「故事方向提案」，给 2~3 个可选方向（每个含一句话前提"
                              "与核心冲突）作为选项让作者挑")
        qs = _gen_questions(outline_llm, clarify_label, idea, req_text,
                            "", min(2, asker.remaining))
        for q, a, src in asker.ask("动笔前确认", qs):
            req_items.append({"id": len(req_items) + 1, "kind": "其他",
                              "req": "（用户确认）{} → {}".format(q, a)})
        if qs:
            req_text = _requirements_text(req_items)   # 答案并入契约

    if req_items:
        kind_count = {}
        for it in req_items:
            kind_count[it["kind"]] = kind_count.get(it["kind"], 0) + 1
        print("想法解析出 {} 条需求（{}）".format(
            len(req_items),
            " · ".join("{} {}".format(v, k) for k, v in kind_count.items())))

    print("第 1/3 步：搭建故事骨架…")
    spine_user = load_prompt(
        "write_spine",
        idea=idea or "（无）", length=str(length),
        knowledge=knowledge, knowledge_source=knowledge_source,
        target_type=article_type, cp_combo=cp_combo, ending_text=ending_text,
        type_hint=RULE_HINTS[article_type], personas=personas_text,
        requirements=req_text,
        rating_note=rating_note,
        draft=(draft[:DRAFT_INPUT_LIMIT] if mode == "expand" else "（无原稿）"),
    )
    spine = outline_llm.chat_json(
        system="你是资深同人作者兼策划。只输出 JSON。",
        user=spine_user, temperature=temperature,
    )
    if not isinstance(spine, dict):
        raise SystemExit("故事骨架生成结果不是 JSON 对象："
                         + json.dumps(spine, ensure_ascii=False)[:300])
    spine_text = json.dumps(spine, ensure_ascii=False, indent=1)
    key_scenes = spine.get("key_scenes") or []
    print("  骨架就绪：核心冲突「{}」，关键场面 {} 个".format(
        str(spine.get("core_conflict") or "")[:40], len(key_scenes)))

    print("第 2/3 步：生成分章大纲（目标 {} 字，约 {} 章）...".format(length, n_chapters))
    if mode == "expand":
        outline_user = load_prompt(
            "write_expand_outline",
            idea=idea or "（无补充要求）", length=str(length), n_chapters=str(n_chapters),
            chapter_chars=str(chapter_chars), knowledge=knowledge,
            knowledge_source=knowledge_source,
            target_type=article_type, cp_combo=cp_combo, ending_text=ending_text,
            type_hint=RULE_HINTS[article_type], personas=personas_text,
            requirements=req_text,
            rating_note=rating_note,
            spine=spine_text,
            draft=draft[:DRAFT_INPUT_LIMIT],
        )
    else:
        outline_user = load_prompt(
            "write_outline",
            idea=idea, length=str(length), n_chapters=str(n_chapters),
            chapter_chars=str(chapter_chars), knowledge=knowledge,
            knowledge_source=knowledge_source, spine=spine_text,
            target_type=article_type, cp_combo=cp_combo, ending_text=ending_text,
            type_hint=RULE_HINTS[article_type], personas=personas_text,
            requirements=req_text,
            rating_note=rating_note,
        )
    outline = outline_llm.chat_json(
        system="你是资深同人作者兼策划。只输出 JSON。",
        user=outline_user, temperature=temperature,
    )
    title = str(outline.get("title") or "未命名").strip()
    chapters_spec = outline.get("chapters") or []
    if not chapters_spec:
        raise SystemExit("大纲生成结果里没有 chapters 字段：" + json.dumps(outline, ensure_ascii=False)[:300])
    # 章数校准：偏离计划先提示；严重偏离（少一半以上 / 多一倍以上）带反馈重问一次
    if len(chapters_spec) != n_chapters:
        print("  大纲给出 {} 章（计划约 {} 章）".format(len(chapters_spec), n_chapters))
    if len(chapters_spec) < max(1, n_chapters // 2) or len(chapters_spec) > n_chapters * 2:
        print("  章数与目标偏差过大，带反馈重问一次…")
        retry_user = outline_user + (
            "\n\n【返工要求】你上一版给的 chapters 是 {} 章，与目标约 {} 章偏差过大"
            "（那会导致单章体量失控）。请重新输出完整 JSON：chapters 严格 {} 章，"
            "每章约 {} 字，仍须覆盖故事骨架的全部关键场面。".format(
                len(chapters_spec), n_chapters, n_chapters, chapter_chars))
        try:
            retry = outline_llm.chat_json(
                system="你是资深同人作者兼策划。只输出 JSON。",
                user=retry_user, temperature=max(0.3, temperature - 0.3),
            )
            rc = (retry.get("chapters") or []) if isinstance(retry, dict) else []
            if rc and abs(len(rc) - n_chapters) < abs(len(chapters_spec) - n_chapters):
                print("  重问后 {} 章，采用新版".format(len(rc)))
                outline, chapters_spec = retry, rc
                title = str(outline.get("title") or title).strip()
            else:
                print("  重问结果没有更好，沿用原大纲")
        except Exception as e:  # noqa: BLE001 重问失败沿用原大纲
            print("  重问失败，沿用原大纲：{}".format(str(e)[:80]))

    print("章节安排（不合心意可随时停止，改想法后重跑）：")
    for i, ch in enumerate(chapters_spec, 1):
        cov = ch.get("covers") or []
        cov_s = "（兑现需求 {}）".format("、".join(str(c) for c in cov)) if cov else ""
        print("  第 {} 章《{}》{}：{}".format(
            i, ch.get("title") or f"第{i}章", cov_s,
            re.sub(r"\s+", " ", str(ch.get("summary") or ""))[:60]))

    print("第 3/3 步：逐章生成（共 {} 章；连续性档案 + 自查修订{}）...".format(
        len(chapters_spec), "开启" if self_revise else "关闭"))
    print("# 进度：章节 0/{}".format(len(chapters_spec)))
    plot_anchor = "（无原稿，按大纲与想法自由发挥）"
    if mode == "expand":
        plot_anchor = ("下面是作者的原稿。情节、人物与结局以此为准，扩写只能增补细节与场景，"
                       "不得改动、删减或新增情节走向：\n" + draft[:DRAFT_INPUT_LIMIT])
    bible_lines = ["【开局状态】" + str(spine.get("start_state") or ""),
                   "【终局目标】" + str(spine.get("end_state") or ""),
                   "【核心冲突】" + str(spine.get("core_conflict") or "")]

    # ---- 提问点 ②：大纲确认——押了赌注的细节当面问清，答案进连续性档案 ----
    if asker.remaining:
        qs = _gen_questions(outline_llm, "大纲确认（动笔前最后一步）", idea, req_text,
                            _story_map(chapters_spec, 0), min(2, asker.remaining))
        for q, a, src in asker.ask("大纲细节确认", qs):
            bible_lines.append("【用户决策】{} → {}".format(q, a))

    chapter_texts = []
    for i, ch in enumerate(chapters_spec, 1):
        prev_tail = chapter_texts[-1][-1200:] if chapter_texts else ""
        prev_head = chapter_texts[-1][:300] if chapter_texts else ""
        # 字数锚：已写章节的平均长度，帮模型校准本章体量（避免越写越短）
        band = ("本章目标约 {} 字，不要低于目标的 85%，也不要超过 130%。"
                .format(chapter_chars))
        if chapter_texts:
            avg = sum(_wc(t) for t in chapter_texts) / len(chapter_texts)
            size_anchor = "前面已写 {} 章，平均每章约 {} 字；{}".format(
                len(chapter_texts), int(avg), band)
        else:
            size_anchor = "本章是开篇；" + band
        chapter_json = json.dumps(ch, ensure_ascii=False, indent=1)
        bible_text = "\n".join(bible_lines)
        chapter_user = load_prompt(
            "write_chapter",
            idea=idea, title=title,
            chapter_no=str(i), total_chapters=str(len(chapters_spec)),
            chapter_json=chapter_json,
            knowledge=knowledge, prev_tail=prev_tail or "（本章是第一章）",
            prev_head=prev_head or "（本章是第一章）",
            size_anchor=size_anchor,
            chapter_chars=str(chapter_chars),
            target_type=article_type, cp_combo=cp_combo, ending_text=ending_text,
            type_hint=RULE_HINTS[article_type], plot_anchor=plot_anchor,
            personas=personas_text, bible=bible_text,
            story_map=_story_map(chapters_spec, i),
            requirements=req_text,
            lore_tools=lore_tools,
            style_skill=style_skill,
            rating_note=rating_note,
        )
        chapter_system = ("你是文笔出色的同人作者。只输出小说正文本身，不要章节号、标题、"
                          "任何解释或作者的话。")
        text = _gen_chapter_text(
            chapter_llm, chapter_system, chapter_user, temperature,
            query_rounds=query_rounds, char_limit=query_char_limit,
            entries=lore_entries, files=lore_filelist).strip()
        # 过短基本等于生成失败（截断/跑偏）：带明确反馈重写一次，取更长的一版
        wc0 = _wc(text)
        if wc0 < chapter_chars * 0.35:
            print("  第 {} 章过短（约 {} 字），带提示重写一次…".format(i, wc0))
            try:
                retry = chapter_llm.chat(
                    system=chapter_system,
                    user=chapter_user + "\n\n【返工要求】上一版只有约 {} 字，远低于 {} 字"
                                        "目标，等于没写完。请完整重写本章全文，体量达标，"
                                        "情节点全部落实。".format(wc0, chapter_chars),
                    temperature=temperature,
                ).strip()
                if _wc(retry) > wc0:
                    text = retry
                    print("  重写后约 {} 字".format(_wc(text)))
                else:
                    print("  重写更短，保留原版")
            except Exception as e:  # noqa: BLE001 重写失败保留原稿
                print("  重写失败，保留原稿：{}".format(str(e)[:80]))
        if self_revise:
            print("  第 {} 章自查修订中…".format(i))
            try:
                revised = revise_llm.chat(
                    system="你是苛刻的审稿编辑。只输出修订后的本章全文，不要任何解释。",
                    user=load_prompt("self_revise", chapter_json=chapter_json,
                                     bible=bible_text, personas=personas_text,
                                     requirements=req_text,
                                     chapter_text=text,
                                     style_skill=style_skill,
                                     rating_note=rating_note),
                    temperature=0.3, timeout=300, retries=2,
                ).strip()
                if len(revised) >= len(text) * 0.5:
                    text = revised
                    print("  第 {} 章自查修订完成（约 {} 字）".format(i, len(text)))
                else:
                    print("  第 {} 章修订输出异常偏短，保留原稿".format(i))
            except Exception as e:  # noqa: BLE001 自查失败保留原稿
                print("  第 {} 章自查失败，保留原稿：{}".format(i, str(e)[:80]))
        chapter_texts.append(text)
        # 连续性档案更新：提取本章新事实，供后续章节防矛盾
        try:
            facts = bible_llm.chat_json(
                system="你是连续性管理员。只输出 JSON。",
                user=load_prompt("bible_update", bible="\n".join(bible_lines),
                                 chapter_text=text[:6000]),
                temperature=0.2, timeout=120, retries=1,
            )
            for fact in (facts.get("facts") or [])[:8]:
                if isinstance(fact, str) and fact.strip():
                    bible_lines.append("· " + fact.strip())
            bible_lines = _cap_bible(bible_lines)
        except Exception:  # noqa: BLE001 档案更新失败不阻塞
            pass
        wc = _wc(text)
        note = ""
        if wc < chapter_chars * 0.6:
            note = "（偏短，低于目标 60%）"
        elif wc > chapter_chars * 1.5:
            note = "（偏长，超出目标 50%）"
        print("  第 {} 章完成（约 {} 字）{}".format(i, wc, note))
        print("# 进度：章节 {}/{}".format(i, len(chapters_spec)))

    # ---- 终局统筹：带着全文脉络重看末章收尾（防结尾泄气/偏题） ----
    if bool(wcfg.get("final_pass", True)) and chapter_texts:
        print("终局统筹：带着全文脉络重看末章收尾…")
        print("# 进度：统筹 1/1")
        try:
            revised = revise_llm.chat(
                system="你是苛刻的审稿编辑。只输出修订后的末章全文，不要任何解释。",
                user=load_prompt(
                    "final_pass",
                    idea=idea, title=title,
                    total_chapters=str(len(chapters_spec)),
                    chapter_json=json.dumps(chapters_spec[-1], ensure_ascii=False,
                                           indent=1),
                    chapter_text=chapter_texts[-1],
                    story_so_far=_story_so_far(chapters_spec, chapter_texts[:-1]),
                    bible="\n".join(bible_lines),
                    ending_text=ending_text, type_hint=RULE_HINTS[article_type],
                    personas=personas_text, knowledge=knowledge,
                    requirements=req_text,
                    style_skill=style_skill,
                    rating_note=rating_note,
                ),
                temperature=0.3, timeout=300, retries=1,
            ).strip()
            old_wc = len(re.sub(r"\s", "", chapter_texts[-1]))
            new_wc = len(re.sub(r"\s", "", revised))
            if new_wc >= old_wc * 0.6:
                chapter_texts[-1] = revised
                print("  末章已统筹（约 {} 字 -> {} 字）".format(old_wc, new_wc))
            else:
                print("  统筹输出过短（{} 字），保留原末章".format(new_wc))
        except Exception as e:  # noqa: BLE001 统筹失败不阻塞
            print("  终局统筹失败，保留原末章：{}".format(str(e)[:80]))

    mode_name = mode_label
    length_note = "目标篇幅：约 {} 字 ｜ ".format(length) if mode == "auto" else \
        "原稿约 {} 字 -> 扩充目标约 {} 字 ｜ ".format(len(draft), length)
    body = _assemble_body(chapters_spec, chapter_texts)

    # ---- 结局走向校验：实际收尾是否兑现了用户要的 HE/BE ----
    # 不符时自动修复一次末章收尾并复检；仍不符才在文首标注（标注行为保留）。
    ending_note = ""
    if ending != "不限" and bool(wcfg.get("ending_check", True)):
        print("结局走向校验（要求：{}）…".format(ending))
        print("# 进度：校验 1/1")

        def _check():
            return ending_check_llm.chat_json(
                system="你是审稿编辑。只输出 JSON。",
                user=load_prompt("ending_check", ending=ending,
                                 story=_ending_window(body)),
                temperature=0.2, timeout=180, retries=1,
            )

        try:
            verdict = _check()
            actual = str(verdict.get("actual") or "").strip() or "不确定"
            if bool(verdict.get("match")):
                print("  结局校验通过：实际走向「{}」，符合要求".format(actual))
            else:
                print("  ⚠ 结局校验未通过：实际「{}」，要求「{}」——自动修复一次收尾…"
                      .format(actual, ending))
                repaired = False
                try:
                    revised = revise_llm.chat(
                        system="你是审稿编辑，负责把结尾修到指定的结局走向。"
                               "只输出修订后的末章全文，不要任何解释。",
                        user=load_prompt(
                            "ending_fix",
                            ending=ending, ending_text=ending_text,
                            verdict_note=str(verdict.get("note") or "结尾收得太软"),
                            idea=idea or "（无）", title=title,
                            total_chapters=str(len(chapters_spec)),
                            chapter_json=json.dumps(chapters_spec[-1], ensure_ascii=False,
                                                   indent=1),
                            chapter_text=chapter_texts[-1],
                            story_so_far=_story_so_far(chapters_spec, chapter_texts[:-1]),
                            bible="\n".join(bible_lines),
                            type_hint=RULE_HINTS[article_type], personas=personas_text,
                            requirements=req_text,
                            style_skill=style_skill,
                            rating_note=rating_note,
                        ),
                        temperature=0.3, timeout=300, retries=1,
                    ).strip()
                    old_wc = _wc(chapter_texts[-1])
                    if _wc(revised) >= old_wc * 0.6:
                        chapter_texts[-1] = revised
                        body = _assemble_body(chapters_spec, chapter_texts)
                        print("  收尾已重写（约 {} 字 -> {} 字），复检…".format(
                            old_wc, _wc(revised)))
                        v2 = _check()
                        if bool(v2.get("match")):
                            repaired = True
                            actual = str(v2.get("actual") or "").strip() or actual
                            print("  复检通过：实际走向「{}」，已修复到要求的结局".format(actual))
                        else:
                            actual = str(v2.get("actual") or "").strip() or actual
                            verdict = v2
                            print("  复检仍未通过：实际「{}」".format(actual))
                    else:
                        print("  修复稿过短（{} 字），放弃修复".format(_wc(revised)))
                except Exception as e:  # noqa: BLE001 修复失败不阻塞
                    print("  自动修复失败：{}".format(str(e)[:80]))
                if repaired:
                    ending_note = ("> ✓ 结局走向校验：结尾已自动修正，实际收尾「{}」"
                                   "符合要求的「{}」。\n\n".format(actual, ending))
                else:
                    ending_note = ("> ⚠ 结局走向校验：实际收尾倾向「{}」，与要求的「{}」"
                                   "不一致——审稿意见：{}\n\n".format(
                                       actual, ending,
                                       verdict.get("note") or "结尾收得太软"))
                    print("  ⚠ 结局校验未通过：实际「{}」，要求「{}」（已在文首标注）"
                          .format(actual, ending))
        except Exception as e:  # noqa: BLE001 校验失败不阻塞
            print("  结局校验失败，跳过：{}".format(str(e)[:80]))

    # ---- 想法兑现校验：成文逐条对照需求清单，结果清单上墙到文首 ----
    idea_note = ""
    if req_items and bool(wcfg.get("idea_check", True)):
        print("想法兑现校验（{} 条需求）…".format(len(req_items)))
        print("# 进度：想法校验 1/1")
        try:
            verdict = idea_check_llm.chat_json(
                system="你是审稿编辑。只输出 JSON。",
                user=load_prompt(
                    "idea_check",
                    requirements=req_text,
                    story_map=_story_map(chapters_spec, len(chapters_spec) + 1),
                    story=_ending_window(body, head=8000, tail=20000),
                ),
                temperature=0.2, timeout=240, retries=1,
            )
            by_id = {it["id"]: it for it in req_items}
            hit = miss = 0
            for r in (verdict.get("items") or []):
                try:
                    rid = int(r.get("id"))
                except (TypeError, ValueError):
                    continue
                if rid not in by_id:
                    continue
                if bool(r.get("hit")):
                    hit += 1
                else:
                    miss += 1
                    print("  ✗ [{}] {}——{}".format(
                        by_id[rid]["kind"], by_id[rid]["req"],
                        str(r.get("note") or "").strip() or "未见落实"))
            print("  想法兑现：{}/{}".format(hit, hit + miss))
            idea_note = _idea_note_text(by_id, verdict)
        except Exception as e:  # noqa: BLE001 校验失败不阻塞
            print("  想法兑现校验失败，跳过：{}".format(str(e)[:80]))

    full = (_header(title, length_note, category, ending_text, mode_name,
                    knowledge_source, idea, rating_label) + ending_note
            + _qa_note_text(asker.qa_log) + idea_note + body)

    path = _output_path(title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(full)
    print("完成：全文约 {} 字 -> {}".format(_wc(full), path))
    return path

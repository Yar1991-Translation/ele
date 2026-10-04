# -*- coding: utf-8 -*-
"""配置项元数据：config.yaml 与 .env 的**单一事实来源**。

前端拿到 /api/config-schema 后自动生成表单，ALLOWED_CONFIG 也由这里派生——
这样「代码能调 / 白名单允许 / 界面有入口」三处不会再各写各的而漂移。

加一个新配置项只要三步：
  1. 在 FIELDS（或 ENV_FIELDS）里加一条；
  2. 在对应 pipeline/spider 代码里 cfg.get(...) 读它；
  3. 前端什么都不用改，表单会自己长出来。
"""

# 类型名 -> server._coerce 里对应的 Python 类型（保持现有转换逻辑不变）
TYPE_MAP = {"str": str, "int": int, "float": float,
            "bool": bool, "list": list, "agentlist": "agentlist",
            "providerlist": "providerlist"}

# 分组：顺序即界面顺序
GROUPS = [
    ("basic", "基础", "登录、模型与目标 tag——跑起来最少只需要配这一组"),
    ("crawl", "爬取", "怎么从 Lofter 抓文章"),
    ("filter", "过滤", "排除乙女向与图片帖、碎片帖"),
    ("distill", "蒸馏", "把文章提炼成知识库"),
    ("write", "写作", "生成文章的默认目标与质量开关"),
    ("team", "团队润色", "多 Agent 讨论润色（仅「团队润色」方式生效）"),
    ("chars", "角色卡", "从同人文深度蒸馏人物卡"),
    ("providers", "模型提供商", ".env 之外的更多 OpenAI 兼容提供商；之后在「模型分配」里用「提供商名/模型名」引用"),
    ("models", "模型分配", "每个阶段用哪个模型，可交叉对照；可写「提供商名/模型名」；留空 = 用主模型"),
]


def F(path, typ, default, label, help, group, advanced=False, **kw):
    d = {"path": path, "type": typ, "default": default, "label": label,
         "help": help, "group": group, "advanced": bool(advanced)}
    d.update(kw)
    return d


FIELDS = [
    # ---------------- 基础（.env 里那几个也在这里归到 basic，前端一起显示） ----------------
    F("crawl.tag", "str", "", "标签名",
      "Lofter 上的话题标签，直接写中文，例如「洲回响」。这是唯一必填项。",
      "basic", required=True, placeholder="洲回响"),
    F("crawl.sort", "str", "new", "翻页方式",
      "new=按最新翻页（最快，但平台单次上限约 1099 篇）；date=按天回溯（慢，可爬到更早的）；"
      "total/week/month=按热度/周榜/月榜。",
      "basic", choices=[("new", "最新优先"), ("date", "按天回溯"),
                        ("total", "总热度"), ("week", "本周热门"), ("month", "本月热门")]),
    F("crawl.max_count", "int", 0, "爬取篇数上限",
      "0 = 不限制。第一次试跑建议填 20，确认没问题再放开。",
      "basic", unit="篇", min=0, max=100000),

    # ---------------- 爬取 ----------------
    F("crawl.batch_size", "int", 100, "每批拉取条数",
      "一次请求向 Lofter 要多少篇。一般不用改。", "crawl", advanced=True, unit="条", min=10, max=200),
    F("crawl.request_interval_min", "float", 3.5, "批间等待下限",
      "两批请求之间随机等待的下限。设得越小爬得越快，也越容易触发限流。",
      "crawl", unit="秒", min=0, max=120, step=0.1),
    F("crawl.request_interval_max", "float", 6.0, "批间等待上限",
      "两批请求之间随机等待的上限。下限=上限即固定等待。", "crawl",
      unit="秒", min=0, max=300, step=0.1),
    F("crawl.min_request_interval", "float", 3.0, "等待下限保护",
      "无论上面怎么填，实际等待都不会低于这个值——Lofter 对接口有频控。"
      "改小=自担限流风险；填 0 表示不保护。", "crawl", unit="秒", min=0, max=60, step=0.5),
    F("crawl.rate_limit_backoff", "int", 600, "限流退避时长",
      "撞到限流后等多久重试。连续 5 次限流会自动停止并保存进度。", "crawl",
      advanced=True, unit="秒", min=30, max=3600),
    F("crawl.min_hot", "int", 0, "热度门槛",
      "热度低于这个数的文章不保存。0 = 全部都要。", "crawl", advanced=True, min=0, max=100000),
    F("crawl.start_date", "str", "", "只收此日期之后",
      "填 2026-01-01 就只收这天之后的文章；留空 = 不限。仅在「按天回溯」下有意义。",
      "crawl", advanced=True, placeholder="2026-01-01"),
    F("crawl.empty_day_limit", "int", 14, "按天回溯停止条件",
      "按天往回爬时，连续多少天没有新文章就停下来。", "crawl", advanced=True, unit="天", min=1, max=60),
    F("crawl.skip_img_posts", "bool", False, "爬取时就丢弃图片帖",
      "打开后图片帖根本不入库。默认关闭：原始数据全量保留，由「过滤」层零成本排除，"
      "这样改了过滤规则不用重爬。", "crawl", advanced=True),
    F("crawl.save_txt_backup", "bool", True, "另存可读 txt",
      "每篇同时存一份 txt 到 data/posts/txt/，方便直接翻看。", "crawl", advanced=True),
    F("crawl.debug_save_raw", "bool", True, "保存原始响应",
      "把可疑的接口原始响应存到 data/posts/raw/（最多留 20 份），排查解析问题用。",
      "crawl", advanced=True),

    # ---------------- 过滤 ----------------
    F("filter.text_only", "bool", True, "只留纯文字帖",
      "排除带图的帖子（那些只配一小段字的图片帖）。这是最有效的一步。", "filter"),
    F("filter.min_length", "int", 300, "正文短于此不收",
      "短于这些字的算碎片帖（转发语、一句话感慨），排除掉。", "filter", unit="字", min=0, max=5000),
    F("filter.keywords", "list", [], "关键词黑名单",
      "标题或正文里出现这些词就直接排除（不花 AI 调用）。一行一个，或用逗号分隔。",
      "filter", placeholder="乙女向\n梦女\n女主"),
    F("filter.llm_judge", "bool", True, "用 AI 逐篇判定",
      "关掉则不做任何 AI 判定，全部保留且不分类。省钱但分类知识库也就没有了。", "filter"),
    F("filter.confidence_threshold", "float", 0.6, "判定置信度门槛",
      "AI 认为是乙女向的信心低于这个数就不排除（宁可放过）。调高=排除更狠。",
      "filter", advanced=True, min=0, max=1, step=0.05),
    F("filter.content_sample_chars", "int", 600, "正文取样字数",
      "每篇只取前面这么多字给 AI 判定，省 token。太短可能判不准。", "filter",
      advanced=True, unit="字", min=100, max=4000),

    # ---------------- 蒸馏 ----------------
    F("distill.focus", "list", ["characters", "style", "tropes", "warnings"], "生成哪些知识库",
      "characters=人设与关系，style=文风，tropes=桥段与爽点，warnings=雷点。"
      "提炼永远全量做，改这里只影响最后渲染出哪几份。",
      "distill", choices=[("characters", "人设与关系"), ("style", "文风"),
                          ("tropes", "桥段与爽点"), ("warnings", "雷点")]),
    F("distill.min_text_chars", "int", 100, "正文短于此不提炼", "太短的没东西可提炼。",
      "distill", unit="字", min=0, max=2000),
    F("distill.reduce_batch_size", "int", 20, "合并分批大小",
      "一次给 AI 多少篇的提炼结果去合并。超过这个数会自动分两级合并。", "distill",
      advanced=True, unit="篇", min=5, max=100),
    F("distill.batch_char_limit", "int", 60000, "单批合并字数上限",
      "一次合并调用最多塞多少字。占内存和 token 的平衡点。", "distill",
      advanced=True, unit="字", min=10000, max=200000),

    # ---------------- 写作 ----------------
    F("write.article_type", "str", "CP向", "默认文章类型",
      "单人向 / CP向 / 其他。选单人向时 CP 组合会强制变成「微量」。", "write",
      choices=[("单人向", "单人向"), ("CP向", "CP向"), ("其他", "其他")]),
    F("write.cp_combo", "str", "男男", "默认 CP 组合",
      "微量=几乎不写感情线；其余为配对性别组合。", "write",
      choices=[("微量", "微量"), ("男女", "男女"), ("男男", "男男"),
               ("女女", "女女"), ("多CP", "多CP"), ("无CP", "无CP")]),
    F("write.ending", "str", "不限", "默认结局走向",
      "HE=好结局，BE=坏结局，开放式=不给结论。", "write",
      choices=[("HE", "HE（好结局）"), ("BE", "BE（坏结局）"),
               ("开放式", "开放式"), ("不限", "不限")]),
    F("write.rating", "str", "r12", "内容分级",
      "生成内容的硬性边界，注入全部生成与审校环节并标注在成文头部："
      "R12=全年龄；R16=重暴力/暗黑可直白、性只作暗示；R18=无限制成人向；"
      "R18G=无限制+血腥残酷描写。唯一硬边界：涉及未成年人的性内容在任何模式下都禁止。",
      "write",
      choices=[("r12", "R12（普遍级）"), ("r16", "R16（辅导级）"),
               ("r18", "R18（无限制）"), ("r18g", "R18G（无限制·残酷描写）")]),
    F("write.mode", "str", "auto", "默认写作方式",
      "auto=自动生成，quick=关键词速写（一个关键词+选几张人物卡+可选全员登场），"
      "self=我写的原样收稿，polish=润色原稿，expand=扩充原稿，team=团队润色。",
      "write", advanced=True,
      choices=[("auto", "自动生成"), ("quick", "关键词速写"), ("self", "我自己写"),
               ("polish", "润色原稿"), ("expand", "扩充原稿"), ("team", "团队润色")]),
    F("write.length", "int", 8000, "目标篇幅",
      "生成文章大概多少字。8000 字约 3~4 章。", "write", unit="字", min=500, max=100000),
    F("write.chapter_chars", "int", 2500, "单章字数",
      "章数 = 目标篇幅 ÷ 单章字数。", "write", unit="字", min=500, max=20000),
    F("write.temperature", "float", 0.8, "写作温度",
      "越高越发散、有想象力；越低越稳、贴合设定。0.7~0.9 之间比较合适。",
      "write", min=0, max=2, step=0.1),
    F("write.self_revise", "bool", True, "逐章自查修订",
      "每写完一章让 AI 以审稿人身份检查并改一遍。质量更稳，但耗时翻倍。",
      "write", advanced=True),
    F("write.final_pass", "bool", True, "末章统筹",
      "写完全文后带着全文脉络重看一遍结尾，防止结尾泄气。", "write"),
    F("write.ending_check", "bool", True, "结局校验",
      "写完后核对实际收尾是否兑现了你要的 HE/BE；不符会自动修复一次收尾，"
      "仍不符才在文首标注。", "write"),
    F("write.idea_check", "bool", True, "想法兑现校验",
      "写完后把成文逐条对照你的想法验收，「想法兑现清单」放在文首；"
      "关闭可省一次 AI 调用。", "write"),
    F("write.ask_enabled", "bool", True, "写作中向你提问",
      "想法有歧义、细节押了赌注时，AI 会在动笔前停下来问你（GUI 任务条上答，"
      "命令行里直接打字）。关掉则全程不打扰。", "write"),
    F("write.ask_max", "int", 3, "每篇最多提问数",
      "提问预算：问满即不再打扰。0 = 从不提问。", "write",
      min=0, max=10),
    F("write.ask_timeout", "int", 300, "提问等待时长",
      "在界面上等多久没回答就按建议继续（秒）。命令行直跑会一直等你。",
      "write", advanced=True, unit="秒", min=30, max=3600),
    F("write.use_personas", "bool", True, "注入人物卡",
      "关掉后写作时完全不给人物设定，纯靠知识库。", "write", advanced=True),
    F("write.persona_char_limit", "int", 4000, "单张人物卡注入上限",
      "每张卡最多取多少字，防止百科卡塞满每一章。", "write", advanced=True,
      unit="字", min=200, max=20000),
    F("write.knowledge_char_limit", "int", 6000, "单份知识库注入上限",
      "每份知识库最多取多少字。", "write", advanced=True, unit="字", min=500, max=30000),
    F("write.persona_source", "str", "both", "人物卡来源",
      "两者结合=官方卡+蒸馏卡；仅蒸馏卡=只用同人语境形象；仅官方卡=只用官方设定。",
      "write", advanced=True,
      choices=[("both", "两者结合"), ("distilled", "仅蒸馏卡"), ("official", "仅官方卡")]),
    F("write.official_weight", "int", 30, "官方档案权重",
      "0~100。数值越高越以官方设定为准；低则以同人语境形象为准。", "write",
      advanced=True, min=0, max=100, step=10),
    F("write.gti_official_only", "bool", True, "配角只用官方卡",
      "除了主角（@名字:主役）之外的角色一律只用官方卡，不掺同人二设；"
      "出场阵容也限定在官方人物卡名单内。", "write", advanced=True),
    F("write.style_skill", "str", "精简", "去AI味规范",
      "写作/自查/润色/团队评审全链路注入 Humanizer 去AI味规范："
      "精简=核心规则卡（每次调用约多 5K token）；完整=全量规则表（约多 30K token，慎用）；关=不注入。",
      "write", choices=[("关", "关"), ("精简", "精简（推荐）"), ("完整", "完整（更贵）")]),
    F("write.query_tools", "bool", True, "写作前可查资料",
      "逐章动笔前允许 AI 先查询设定/剧情文件（素材页「设定与剧情」，data/lore/）"
      "与人物卡全文再落笔。每章多 0~2 次调用，资料已够时模型会直接开写。", "write"),
    F("write.query_rounds", "int", 2, "每章查询轮数上限",
      "每章动笔前最多几轮资料查询，0 = 关闭查询。", "write",
      advanced=True, unit="轮", min=0, max=5),
    F("write.query_char_limit", "int", 4000, "单条查询结果上限",
      "每条查询返回的资料最多多少字，防止大文件塞爆上下文。", "write",
      advanced=True, unit="字", min=500, max=20000),

    # ---------------- 团队润色 ----------------
    F("team.rounds", "int", 1, "讨论轮数",
      "几位编辑各评一轮、主笔改一稿算一轮。轮数越多越精，但花的调用越多。", "team",
      unit="轮", min=1, max=5),
    F("team.editor_model", "str", "", "主笔模型",
      "负责汇总大家意见并改稿的模型。可写「提供商名/模型名」用别的提供商；留空 = 用主模型。",
      "team", placeholder="留空 = 主模型"),
    F("team.agents", "agentlist", [], "团队成员",
      "每位成员可指定模型（支持「提供商名/模型名」跨提供商交叉讨论；留空=主模型）与思考强度，"
      "各自负责一个视角。建议几位成员配不同提供商的模型。", "team"),

    # ---------------- 角色卡 ----------------
    F("character_cards.min_mentions", "int", 2, "至少几篇提及才建卡",
      "提到次数太少的角色建不出有意义的卡，会被跳过。", "chars", unit="篇", min=1, max=20),
    F("character_cards.max_articles_per_char", "int", 12, "每角色最多读多少篇",
      "防止高频角色吃掉大量 token。", "chars", unit="篇", min=1, max=100),
    F("character_cards.batch_article_chars", "int", 12000, "每批文章字数",
      "分批读原文时每批塞多少字。", "chars", advanced=True, unit="字", min=2000, max=80000),
    F("character_cards.article_input_limit", "int", 8000, "单篇读取上限",
      "单篇原文最多取多少字。", "chars", advanced=True, unit="字", min=500, max=30000),
    F("character_cards.concurrency", "int", 3, "并发数",
      "同时跑几个角色的蒸馏。你的模型支持多并发时可以调大。", "chars",
      advanced=True, unit="个", min=1, max=8),

    # ---------------- 模型提供商 ----------------
    F("providers", "providerlist", [], "更多提供商",
      "除 .env 主提供商外的其他 OpenAI 兼容提供商（base_url + api_key）。"
      "配置后在「模型分配」与团队成员里用「提供商名/模型名」引用，"
      "例如 write_chapter 填 deepseek/deepseek-chat。", "providers"),

    # ---------------- 模型分配 ----------------
    F("models.filter", "str", "", "过滤（判定+分类）",
      "量大、判断简单，适合便宜的快模型。可写「提供商名/模型名」。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.distill_map", "str", "", "蒸馏·每篇先提炼",
      "每篇文章的初步提炼（产出中间草稿）。可写「提供商名/模型名」。留空 = 主模型。", "models", placeholder="留空 = 主模型"),
    F("models.distill_reduce", "str", "", "蒸馏·合并成知识库",
      "把多篇提炼合并成知识库，质量敏感，适合强模型。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.character_cards", "str", "", "角色卡蒸馏", "留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.write_outline", "str", "", "写作·故事骨架与大纲", "留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.write_chapter", "str", "", "写作·逐章正文",
      "可与「写作·修订」配不同提供商的模型，形成交叉对照。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.write_revise", "str", "", "写作·章节自查修订",
      "自查修订、末章统筹与结局修复共用。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.bible_update", "str", "", "写作·连续性档案",
      "每章写完后提取新事实进档案。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.ending_check", "str", "", "写作·结局校验",
      "核对实际收尾是否兑现要求走向（只判定不改稿）。换一家提供商的模型校验更客观。留空 = 主模型。",
      "models", placeholder="留空 = 主模型"),
    F("models.idea_check", "str", "", "写作·想法兑现校验",
      "成文逐条对照需求清单验收（只判定不改稿）。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.polish", "str", "", "润色原稿",
      "「润色」方式用的模型。留空 = 主模型。", "models",
      placeholder="留空 = 主模型"),
    F("models.rating_switch", "str", "", "分级达标自动换模型",
      "内容分级达到该档（含更高档）时，写作全流程（含团队润色）自动改用下面的替代模型——"
      "主模型拒写 R16+ 内容时用它。留空 = 不启用。", "models",
      choices=[("", "关"), ("r16", "R16 起"), ("r18", "R18 起"), ("r18g", "仅 R18G")]),
    F("models.rating_model", "str", "", "分级替代模型",
      "上面的切换线达标后使用的模型，支持「提供商名/模型名」（提供商在「模型提供商」分组配置）。"
      "留空 = 不启用。", "models",
      placeholder="例 grok/grok-4.6"),
]

# .env 字段（与 config 分开存，因为含密钥）
ENV_FIELDS = [
    {"path": "LOFTER_COOKIE", "label": "Lofter Cookie", "secret": True, "required": True,
     "help": "浏览器登录 Lofter 后按 F12 → 应用 → Cookie，复制 LOFTER_SESS 的值（或整行 Cookie）。"},
    {"path": "LOFTER_LOGIN_KEY", "label": "Cookie 名（备选）", "secret": False, "required": False,
     "help": "用 Cookie 名+值的方式登录时填，例如 LOFTER_SESS。填了 Cookie 就不用管这两个。"},
    {"path": "LOFTER_LOGIN_AUTH", "label": "Cookie 值（备选）", "secret": True, "required": False,
     "help": "对应上面那个 Cookie 名的值。"},
    {"path": "LLM_BASE_URL", "label": "模型接口地址", "secret": False, "required": True,
     "help": "OpenAI 兼容的接口地址，例如 https://ark.example.com/api/v3"},
    {"path": "LLM_API_KEY", "label": "模型密钥", "secret": True, "required": True,
     "help": "接口的 API Key。"},
    {"path": "LLM_MODEL", "label": "主模型", "secret": False, "required": True,
     "help": "模型名或接入点 ID。各阶段没单独指定模型时都用它。"},
    {"path": "LLM_TIMEOUT", "label": "单次请求超时", "secret": False, "required": False,
     "help": "秒。默认 180。模型响应慢就调大。"},
]

# 预设档位：一键设好一组参数
PRESETS = [
    {"key": "trial", "label": "试跑 20 篇（省钱）",
     "desc": "第一次用选这个：爬 20 篇跑通全流程，确认没问题再放开。",
     "values": {"crawl.max_count": 20, "crawl.sort": "new", "filter.min_length": 300,
                "write.length": 4000, "write.chapter_chars": 2000,
                "character_cards.concurrency": 2}},
    {"key": "standard", "label": "标准",
     "desc": "日常使用的平衡配置。",
     "values": {"crawl.max_count": 0, "filter.min_length": 300,
                "write.length": 8000, "write.chapter_chars": 2500,
                "character_cards.concurrency": 3}},
    {"key": "fine", "label": "精细（更慢更贵）",
     "desc": "写作质量优先：更长的篇幅、开启逐章自查，角色卡并发更高。",
     "values": {"crawl.max_count": 0, "filter.min_length": 400,
                "write.length": 12000, "write.chapter_chars": 2500,
                "write.self_revise": True, "write.final_pass": True,
                "character_cards.concurrency": 4}},
]


# ----------------------------------------------------------------------
def allowed_config():
    """派生给 server.update_config 用的白名单 {path: 类型}。"""
    return {f["path"]: TYPE_MAP[f["type"]] for f in FIELDS}


def fields_json():
    """给前端的完整元数据。"""
    return {
        "fields": FIELDS,
        "groups": [{"key": k, "label": l, "help": h} for k, l, h in GROUPS],
        "env": ENV_FIELDS,
        "presets": PRESETS,
        "types": {k: (v if isinstance(v, str) else v.__name__) for k, v in TYPE_MAP.items()},
    }


def find(path):
    return next((f for f in FIELDS if f["path"] == path), None)


def defaults():
    """全部字段的默认值（写进 config.yaml 的兜底）。"""
    return {f["path"]: f["default"] for f in FIELDS}


def write_defaults_if_missing(path):
    """config.yaml 不存在时（新克隆/新机器部署）按 schema 默认值生成一份。

    返回是否新建了文件；已存在时不动它（保留用户配置）。
    """
    import os
    if os.path.exists(path):
        return False
    cfg = {}
    for dotted, default in defaults().items():
        keys = dotted.split(".")
        cur = cfg
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = default
    import yaml
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 本文件由 GUI 生成/更新（注释会精简，高级配置可直接手改后重启 GUI）\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return True

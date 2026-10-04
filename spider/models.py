"""爬取产物的数据结构。"""
import time
from dataclasses import dataclass, field, asdict


@dataclass
class Post:
    url: str                    # 帖子链接（唯一键）
    post_id: str                # 链接末尾的 post id
    title: str = ""
    author: str = ""
    author_domain: str = ""     # 作者三级域名
    publish_ts: int = 0         # 发表时间戳（毫秒）
    publish_time: str = ""      # 发表时间 yyyy-MM-dd HH:MM
    hot: int = 0
    tags: list = field(default_factory=list)
    content_md: str = ""        # 正文（markdown 化）
    long_text: str = ""         # 长文章正文（纯文本）
    images: list = field(default_factory=list)   # 配图/插图链接
    post_type: str = ""         # article / text / long / img
    crawl_tag: str = ""         # 爬取时用的 tag
    crawl_time: str = ""        # 爬取时间
    # ---- LLM 分类结果（过滤阶段填充）----
    article_type: str = ""      # 单人向 / CP向 / 其他
    cp_combo: str = ""          # 微量 / 男女 / 男男 / 女女 / 多CP / 无CP
    ending: str = ""            # HE / BE / 开放式 / 未知 / 不适用

    @property
    def text(self):
        """供下游蒸馏用的正文：优先长文，其次普通正文。"""
        return self.long_text if len(self.long_text) >= len(self.content_md) else self.content_md

    def to_dict(self):
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in d.items() if k in known})


def ts_to_str(ms):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ms) / 1000))
    except (ValueError, TypeError, OverflowError):
        return ""


# ---- 文章分类体系（枚举定义，filter/GUI/CLI 共用）----
ARTICLE_TYPES = ["单人向", "CP向", "其他"]
CP_COMBOS = ["微量", "男女", "男男", "女女", "多CP", "无CP"]
ENDINGS = ["HE", "BE", "开放式", "未知", "不适用"]


def category_of(article_type, cp_combo):
    """知识库分组名：文章类型·CP组合，如「CP向·男男」。

    缺分类信息的（旧缓存、LLM 判定失败暂保留的文章）归入「未分类」。
    """
    if not article_type or not cp_combo:
        return "未分类"
    return f"{article_type}·{cp_combo}"


def classify_type(title, content_md, long_text, images):
    """帖子类型。与 lofterSpider 不同：文字优先（我们的下游只消费文字）。

    compositeContent（长文正文字段）非空即为长文，不看长度。
    """
    if long_text.strip():
        return "long"
    if len(content_md.strip()) >= 30:
        return "article" if title.strip() else "text"
    if images:
        return "img"
    return "text"

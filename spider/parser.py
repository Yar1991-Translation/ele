"""DWR 响应解析器。

Lofter 网页版 tag 接口（TagBean.search.dwr）返回的是 DWR 的 JS 脚本文本，形如：

    var s0={};var s1={};
    s0.succeed=true;
    s0.posts=[s1];
    s1.blogPageUrl="https://xxx.lofter.com/post/xxxx";
    s1.title="\u6807\u9898";
    s1.content="<p>...</p>";

lofterSpider 用"按 activityTags 切分 + 非贪婪正则"提取字段，正文里一旦出现 `";`
就会截断。这里改成一个小型分词器：逐条解析 `sN.prop=value;` 赋值，
字符串值按 JS 规则扫描到未转义的引号为止，比正则健壮。
如果未来接口变化，优先改这个文件。
"""
import html
import json
import re
from collections import defaultdict

import html2text

from spider.models import Post, ts_to_str, classify_type

_PROP_RE = re.compile(r"s(\d+)\.(\w+)\s*=")
_IMG_IN_HTML_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
_LOFTER_IMG_RE = re.compile(r"^https?://imglf\d*\.lf\d*\.net", re.I)

_h2t = html2text.HTML2Text()
_h2t.body_width = 0          # 不自动换行
_h2t.ignore_images = False
_h2t.ignore_links = False
_h2t.skip_internal_links = True


def js_unescape(s):
    """还原 DWR 字符串里的 JS 转义（\\uXXXX、\\n、\\" 等），处理代理对。"""
    if "\\" not in s:
        return s
    out = []
    i, n = 0, len(s)
    simple = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
              '"': '"', "'": "'", "\\": "\\", "/": "/"}
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            d = s[i + 1]
            if d == "u" and i + 6 <= n:
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            if d in simple:
                out.append(simple[d])
                i += 2
                continue
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    text = "".join(out)
    if re.search(r"[\ud800-\udfff]", text):  # 修复 emoji 代理对
        try:
            text = text.encode("utf-16", "surrogatepass").decode("utf-16")
        except UnicodeDecodeError:
            pass
    return text


def parse_dwr_objects(text):
    """把 DWR 文本解析成 {对象id: {属性: 值}}。

    字符串值返回未转义后的 str；数值/布尔/引用等原样返回 str。
    """
    objects = defaultdict(dict)
    pos = 0
    n = len(text)
    while pos < n:
        m = _PROP_RE.search(text, pos)
        if not m:
            break
        oid, prop = m.group(1), m.group(2)
        vstart = m.end()
        # 跳过冒号风格的 "number:123" 前缀（请求体格式，正常响应里没有，防御一下）
        if text[vstart:vstart + 1] == '"':
            i = vstart + 1
            while i < n:
                c = text[i]
                if c == "\\":
                    i += 2
                    continue
                if c == '"':
                    break
                i += 1
            raw = text[vstart + 1:i]
            objects[oid][prop] = js_unescape(raw)
            pos = i + 1
        else:
            end = text.find(";", vstart)
            if end == -1:
                end = min(n, vstart + 300)
            objects[oid][prop] = text[vstart:end].strip()
            pos = end + 1
    return objects


def _strip_html(html_text):
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).replace("\n ", "\n").strip()


def _html_to_md(html_text):
    md = _h2t.handle(html_text).strip()
    _h2t.reset()
    return md


def _extract_images(objects, props, content_html):
    urls = []
    # originPhotoLinks 已作为字符串值被解析出来，本身是个 JSON 数组
    raw = props.get("originPhotoLinks", "")
    if raw and raw.strip().startswith("["):
        try:
            for item in json.loads(raw):
                url = item.get("raw") or item.get("orign") or ""
                if url:
                    urls.append(url.split("?imageView")[0])
        except (json.JSONDecodeError, AttributeError):
            pass
    for src in _IMG_IN_HTML_RE.findall(content_html or ""):
        if _LOFTER_IMG_RE.match(src):
            urls.append(src.split("?")[0])
    return list(dict.fromkeys(urls))


def extract_posts(text, crawl_tag=""):
    """从 DWR 响应文本中提取帖子列表。"""
    objects = parse_dwr_objects(text)
    posts = []
    for oid, props in objects.items():
        url = props.get("blogPageUrl", "")
        if "/post/" not in url:
            continue  # blogInfo 对象的 blogPageUrl 是博客主页，跳过

        # 作者名：帖子上没有时通过 blogInfo=sN 引用找
        author = props.get("blogNickName", "")
        if not author:
            ref = str(props.get("blogInfo", "")).strip()
            ref_oid = ref[1:] if ref.startswith("s") else ref
            author = objects.get(ref_oid, {}).get("blogNickName", "")

        author_domain = ""
        dm = re.match(r"https?://([^./]+)\.lofter\.com", url)
        if dm:
            author_domain = dm.group(1)

        publish_ts = int(float(props.get("publishTime", 0)) or 0)
        try:
            hot = int(float(props.get("hot", 0)) or 0)
        except ValueError:
            hot = 0

        tags_raw = props.get("tags") or props.get("tag") or ""
        tags = [t.strip().lower().replace("\u3000", " ") for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        title = (props.get("title") or "").strip()
        content_html = props.get("content") or ""
        composite = props.get("compositeContent") or ""

        content_md = _html_to_md(content_html) if content_html else ""
        long_text = _strip_html(composite) if composite else ""
        images = _extract_images(objects, props, content_html)

        post = Post(
            url=url,
            post_id=url.rstrip("/").split("/")[-1],
            title=title,
            author=author,
            author_domain=author_domain,
            publish_ts=publish_ts,
            publish_time=ts_to_str(publish_ts),
            hot=hot,
            tags=tags,
            content_md=content_md,
            long_text=long_text,
            images=images,
            post_type=classify_type(title, content_md, long_text, images),
            crawl_tag=crawl_tag,
        )
        posts.append(post)
    return posts


def looks_like_dwr_reply(text):
    return "//#DWR-REPLY" in text or bool(_PROP_RE.search(text))


def looks_like_rate_limited(text):
    return "rate-limiting" in text or "post-redirect" in text

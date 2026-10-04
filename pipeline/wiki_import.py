"""萌娘百科角色资料导入：分类 -> 成员页面 -> 清洗 -> data/personas/ 人物卡。

数据来源：萌娘百科 zh.moegirl.org.cn，页面内容采用 CC BY-NC-SA 4.0 授权，
仅供个人阅读与同人创作参考；每张人物卡头部保留来源链接与检索日期。
请求间隔 1.5s，对站点保持礼貌。
"""
import os
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup
import html2text

from spider import storage

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
                     "DeltaForcePersonaImporter/1.0 (personal use)"}
SITE = "https://zh.moegirl.org.cn/"
FETCH_INTERVAL = 1.5
CARD_MAX_CHARS = 6000
NL = "\n"
NL2 = "\n\n"

# 页面正文里的噪音元素：导航框、参考文献、分类栏、目录、脚注标记等
_NOISE_SELECTORS = [
    ".navbox", ".catlinks", ".mw-references-wrap", ".metadata", "#toc",
    ".mw-editsection", "sup.reference", ".reference", ".mw-jump-link",
    "#siteSub", ".printfooter", ".mbox-small", ".ambox", "figure.mw-halign-right",
]

_H2T = html2text.HTML2Text()
_H2T.ignore_links = True
_H2T.ignore_images = True
_H2T.body_width = 0


def _get(url, as_json=False):
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    if as_json:
        return r.json()
    return r.text


def _soup(url):
    return BeautifulSoup(_get(url), "html.parser")


def _url(title):
    return SITE + urllib.parse.quote(title.replace(" ", "_"))


def category_members(category, limit=60):
    """分类下全部页面标题（含下一页翻页；跳过子分类与特殊链接）。

    萌娘百科的 分类页 偶发返回不含成员列表的版本，抓到空结果时重试最多 3 次。
    """
    members, seen = [], set()
    url = SITE + "Category:" + urllib.parse.quote(category)
    while url and len(members) < limit:
        soup = None
        for attempt in range(3):
            soup = _soup(url)
            node = soup.select_one("#mw-pages") or soup
            found = len(node.select("a[href]"))
            if found or attempt == 2:
                break
            print("  分类页偶发为空（第 {} 次），{}s 后重试…".format(attempt + 1, 3 * (attempt + 1)))
            time.sleep(3 * (attempt + 1))
        node = soup.select_one("#mw-pages") or soup
        for a in node.select("a[href]"):
            # 站点有两种渲染：链接文本有时为空，title 属性始终存在
            href = a.get("href", "")
            text = a.get("title") or a.get_text(strip=True)
            if not text or href.startswith("#") or "action=" in href or "redlink=1" in href:
                continue
            if href.startswith("/Category:"):   # 子分类（如音乐）不当作角色页
                continue
            title = urllib.parse.unquote(href.split("#")[0]).lstrip("/")
            if title and title not in seen:
                seen.add(title)
                members.append(title)
        nxt = soup.select_one("#mw-pages a[rel='next']")
        url = SITE + nxt.get("href") if nxt else None
        if url:
            time.sleep(FETCH_INTERVAL)
    return members[:limit]


def _clean_text(raw):
    lines = []
    skipping_banner = False
    for line in raw.splitlines():
        t = line.strip()
        if not t:
            lines.append("")
            continue
        if re.match(r"^\*\*?G\.T\.I\.萌百分部", t):
            skipping_banner = True        # 萌百欢迎横幅：整块跳过
        if skipping_banner:
            if "仅以介绍为目的引用" in t:
                skipping_banner = False
            continue
        if re.match(r"^(查\s*·\s*论\s*·\s*编|分类[:：]|本页面|本分类|Category:)", t):
            continue
        if t.startswith("本文介绍的是"):       # 消歧义行
            continue
        if t.startswith("* 关于") and "详见" in t:
            continue
        t = re.sub(r"\[\d+\]", "", t)          # 残留引注
        lines.append(t)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)     # 折叠空行
    # 从“外部链接/注释/参考资料”小节起截断
    cut = re.search(r"^###+\s*(外部链接|注释|参考资料|参考文献)", text, re.M)
    if cut:
        text = text[:cut.start()]
    return text.strip()


def page_card(title, max_chars=CARD_MAX_CHARS):
    """抓取一个页面并转成人物卡文本（不落盘）。"""
    soup = _soup(_url(title))
    node = soup.select_one(".mw-parser-output") or soup.body or soup
    for sel in _NOISE_SELECTORS:
        for tag in node.select(sel):
            tag.decompose()
    _H2T.reset()
    text = _H2T.handle(str(node))
    text = _clean_text(text)
    if len(text) > max_chars:   # 在段落边界截断
        head = text[:max_chars]
        cut = head.rfind("\n\n")
        text = (head[:cut] if cut > max_chars // 2 else head).rstrip() + "\n<!-- （超长截断） -->"
    return text


def import_category(category, limit=60, card_max_chars=CARD_MAX_CHARS):
    """导入整个分类，返回 [(角色名, 文件路径, 动作)]。"""
    members = category_members(category, limit)
    print("分类「{}」共 {} 个页面：{}".format(category, len(members), "、".join(members)))
    os.makedirs(storage.PERSONAS_DIR, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    results = []
    for i, title in enumerate(members, 1):
        fname = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title).strip() + ".md"
        path = os.path.join(storage.PERSONAS_DIR, fname)
        if os.path.exists(path):
            print("  [{}/{}] 已存在，跳过：{}".format(i, len(members), fname))
            results.append((title, path, "skip"))
            continue
        try:
            text = page_card(title, card_max_chars)
        except Exception as e:  # noqa: BLE001 单页失败不阻塞
            print("  [{}/{}] 抓取失败：{}（{}）".format(i, len(members), title, str(e)[:80]))
            results.append((title, "", "fail"))
            time.sleep(FETCH_INTERVAL)
            continue
        source = _url(title)
        with open(path, "w", encoding="utf-8") as f:
            f.write("# {}{}{}{}".format(
                title, NL2, "> 来源：萌娘百科「{}」（{}）检索于 {}。"
                "内容 CC BY-NC-SA 4.0，仅供个人创作参考。".format(title, source, day),
                NL2, NL) + text + NL)
        print("  [{}/{}] 已导入：{}（{} 字）".format(i, len(members), fname, len(text)))
        results.append((title, path, "ok"))
        time.sleep(FETCH_INTERVAL)
    return results


NL2 = "\n\n"
NL = "\n"

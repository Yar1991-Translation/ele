"""Lofter 网页版 DWR 接口客户端。

接口与参数格式来自对 lofterSpider `l13_like_share_tag.py` 的逆向确认：
POST http://www.lofter.com/dwr/call/plaincall/TagBean.search.dwr
分页靠 c0-param7（偏移）+ c0-param8（上一批最后一条的 publishTime 游标）。
"""
import random
import time
from urllib import parse

import requests

from spider.parser import looks_like_dwr_reply, looks_like_rate_limited

DWR_URL = "https://www.lofter.com/dwr/call/plaincall/TagBean.search.dwr"
HOME_URL = "https://www.lofter.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class RateLimitedError(Exception):
    """触发了 Lofter 的限流跳转。"""


class BadResponseError(Exception):
    """响应不是 DWR 格式（常见原因：cookie 失效被跳到登录页）。"""


class DwRClient:
    def __init__(self, cookie=None, login_key=None, login_auth=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Host": "www.lofter.com",
            "Origin": "https://www.lofter.com",
        })
        if cookie:
            if "=" not in cookie:
                # 只填了一个值（比如从 Application→Cookie 里复制的 LOFTER_SESS 值）
                self.session.cookies.set("LOFTER_SESS", cookie.strip(), domain=".lofter.com")
            else:
                for kv in cookie.split(";"):
                    kv = kv.strip()
                    if not kv or "=" not in kv:
                        continue
                    k, v = kv.split("=", 1)
                    self.session.cookies.set(k, v, domain=".lofter.com")
        elif login_key and login_auth:
            self.session.cookies.set(login_key, login_auth, domain=".lofter.com")

    # ------------------------------------------------------------------
    def check_login(self):
        """粗检登录态：未登录时访问主页通常会被带去登录页。"""
        try:
            r = self.session.get(HOME_URL, timeout=30, allow_redirects=True)
        except requests.RequestException as e:
            raise BadResponseError(f"无法访问 Lofter 主页：{e}")
        if "login" in r.url:
            return False, r.url
        if not self.session.cookies:
            return False, "没有配置任何 cookie"
        return True, r.url

    # ------------------------------------------------------------------
    def _post_dwr(self, data, referer, timeout=60):
        headers = {"Referer": referer}
        r = self.session.post(DWR_URL, data=data, headers=headers, timeout=timeout)
        if r.status_code in (301, 302, 303, 307, 308):
            raise RateLimitedError(f"HTTP {r.status_code} 重定向到 {r.headers.get('Location', '?')}")
        text = r.content.decode("utf-8", errors="replace")
        if looks_like_rate_limited(text) or "rate-limiting" in r.url:
            raise RateLimitedError("响应中出现限流跳转标记")
        if not looks_like_dwr_reply(text):
            raise BadResponseError(
                "响应不是 DWR 数据（可能是 cookie 失效）。"
                "响应开头：" + text[:120].replace("\n", " ")
            )
        return text

    def search_tag(self, tag, sort="date", get_num=100, got_num=0, cursor_ts=0,
                   encoded=False):
        """调一次 tag 搜索。cursor_ts 为上一批最后一条的 publishTime（毫秒）。

        encoded=True 时把 tag 先做 URL 编码再放进参数（lofterSpider 的做法），
        两种形式服务器都认，爬取器会在拿不到数据时自动切换重试。
        """
        tag_param = parse.quote(tag) if encoded else tag
        data = {
            "callCount": "1",
            "httpSessionId": "",
            "scriptSessionId": "${scriptSessionId}187",
            "c0-id": "0",
            "c0-scriptName": "TagBean",
            "c0-methodName": "search",
            "c0-param0": "string:" + tag_param,
            "c0-param1": "number:0",
            "c0-param2": "string:",
            "c0-param3": "string:" + sort,
            "c0-param4": "boolean:false",
            "c0-param5": "number:0",
            "c0-param6": "number:" + str(get_num),
            "c0-param7": "number:" + str(got_num),
            "c0-param8": "number:" + str(int(cursor_ts)),
            "batchId": str(random.randint(100000, 999999)),
        }
        referer = "https://www.lofter.com/tag/{}/{}".format(parse.quote(tag), sort)
        last_err = None
        for attempt in range(3):
            try:
                return self._post_dwr(data, referer)
            except RateLimitedError:
                raise  # 限流交给上层退避处理，不算网络错误
            except (requests.RequestException, BadResponseError) as e:
                last_err = e
                time.sleep(3 * (attempt + 1))
        raise BadResponseError(f"tag 搜索连续 3 次失败：{last_err}")

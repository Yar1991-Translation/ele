"""爬取编排：分页拉取 tag 列表 -> 解析 -> 落盘，支持断点续爬。

分页语义（结合 lofterSpider 的验证行为与实测日志校准）：
- tag 参数用 URL 编码形式（实测原文形式服务器返回 0 条）；
- sort=new：c0-param8 传上一批最旧帖子的 publishTime 做游标往前翻，
  param7 按请求量累加（lofterSpider 同款惯例）。平台单次查询上限约
  1099 篇，翻空即结束——绝大多数 tag 一趟就能爬全；
- sort=date：返回的是以 param8 为终点的时间窗口内的帖子。窗口为空或
  全是旧帖时，把 param8 回退一天开新窗口（got_num 归零），直到连续
  empty_day_limit 天空窗或到达 start_date。慢，但能突破 1099 上限；
- 每批间隔随机 3.5~6s，触发限流退避后原地重试，进度每批落盘；
- 出现可疑响应（要 100 篇却少于 100、或 0 篇）时把原始响应转储到
  data/posts/raw/，便于事后分析接口语义。
"""
import os
import random
import time
from datetime import datetime

from spider.dwr_client import DwRClient, RateLimitedError, BadResponseError
from spider import storage
from spider.parser import extract_posts
from spider.models import Post

DAY_MS = 86400 * 1000


class Crawler:
    def __init__(self, crawl_cfg, cookie=None, login_key=None, login_auth=None,
                 force_login_check=False):
        self.cfg = crawl_cfg
        self.tag = (crawl_cfg.get("tag") or "").strip()
        if not self.tag:
            raise SystemExit("config.yaml 里 crawl.tag 还没填（直接写中文 tag 名即可）")
        self.sort = crawl_cfg.get("sort", "new")
        self.max_count = int(crawl_cfg.get("max_count", 0) or 0)
        self.min_hot = int(crawl_cfg.get("min_hot", 0) or 0)
        self.batch_size = int(crawl_cfg.get("batch_size", 100) or 100)
        self.interval = (float(crawl_cfg.get("request_interval_min", 3.5)),
                         float(crawl_cfg.get("request_interval_max", 6.0)))
        # 间隔下限：Lofter 对接口有频控，低于此值会被抬上来；改小=自担限流风险
        self.min_interval = float(crawl_cfg.get("min_request_interval", 3.0) or 0)
        self.backoff = int(crawl_cfg.get("rate_limit_backoff", 600))
        self.start_date = (crawl_cfg.get("start_date") or "").strip()
        self.save_txt = bool(crawl_cfg.get("save_txt_backup", True))
        self.empty_day_limit = int(crawl_cfg.get("empty_day_limit", 14) or 14)
        self.debug_raw = bool(crawl_cfg.get("debug_save_raw", True))
        # 爬取阶段直接跳过纯图片帖（默认关闭：原始数据全量保存，过滤层零成本排除）
        self.skip_img_posts = bool(crawl_cfg.get("skip_img_posts", False))
        self.force_login_check = force_login_check

        self.client = DwRClient(cookie=cookie, login_key=login_key, login_auth=login_auth)
        self.start_ts = None
        if self.start_date:
            self.start_ts = int(datetime.strptime(self.start_date, "%Y-%m-%d").timestamp() * 1000)

    # ------------------------------------------------------------------
    def _dump_raw(self, batch_no, text):
        """可疑响应转储（原始 DWR 文本），只保留最近 20 份。"""
        try:
            raw_dir = os.path.join(os.path.dirname(storage.POSTS_JSONL), "raw")
            os.makedirs(raw_dir, exist_ok=True)
            name = "batch_{:04d}_{:.0f}.txt".format(batch_no, time.time() % 1e7)
            with open(os.path.join(raw_dir, name), "w", encoding="utf-8") as f:
                f.write(text)
            files = sorted(os.listdir(raw_dir))
            for old in files[:-20]:
                os.remove(os.path.join(raw_dir, old))
            print("  （原始响应已转储 {}/{}）".format(raw_dir, name))
        except OSError:
            pass

    def _save_progress(self, tag_sort, cursor_ts, got_num, oldest_ts, total_saved,
                       encoded_mode, empty_streak, batch_no):
        storage.save_progress({
            "tag": self.tag, "sort": tag_sort,
            "cursor_ts": cursor_ts, "got_num": got_num,
            "oldest_ts": oldest_ts, "total_saved": total_saved,
            "encoded_mode": encoded_mode, "empty_streak": empty_streak,
            "batch_no": batch_no,
        })

    def _fmt_day(self, ts):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    def run(self):
        storage.ensure_dirs()
        ok, info = self.client.check_login()
        if not ok and not self.force_login_check:
            raise SystemExit(
                "登录检查未通过（被跳转到 {}）。\n"
                "填写登录 cookie 的方法（三选一，第 1 种最简单）：\n"
                "  1. F12 → 应用(Application) → Cookie → https://www.lofter.com →\n"
                "     复制 LOFTER_SESS 的值，填进 .env 的 LOFTER_COOKIE=（只填这一个值即可）\n"
                "     （邮箱登录找 NTES_SESS，手机号登录找 LOFTER-PHONE-LOGIN-AUTH）\n"
                "  2. F12 → 网络(Network) → 刷新 → 点任一条 www.lofter.com 请求 →\n"
                "     请求标头(Request Headers) → 复制整行 Cookie 的值填进 LOFTER_COOKIE=\n"
                "  3. 在 .env 里填 LOFTER_LOGIN_KEY=LOFTER_SESS 和 LOFTER_LOGIN_AUTH=对应的值\n"
                "填好后重跑；若确属误判可用 --force 跳过检查。".format(info)
            )

        seen = storage.load_seen_urls()
        progress = storage.load_progress()
        if progress.get("tag") != self.tag or progress.get("sort") != self.sort:
            if progress:
                print("爬取目标变化，重置上次进度")
            progress = {}
        cursor_ts = progress.get("cursor_ts") or int(time.time() * 1000)
        got_num = progress.get("got_num", 0)
        oldest_ts = progress.get("oldest_ts")
        total_saved = progress.get("total_saved", 0)
        encoded_mode = progress.get("encoded_mode", True)   # URL 编码形式优先（实测有效）
        empty_streak = progress.get("empty_streak", 0)
        batch_no = progress.get("batch_no", 0)
        encoded_tried = False
        rate_limit_streak = 0
        reached_start = False

        low, high = sorted((float(self.interval[0]), float(self.interval[1])))
        eff = max(self.min_interval, low)
        print("开始爬取 tag「{}」（排序 {}，已存 {} 篇，本次从游标 {} 继续）".format(
            self.tag, self.sort, total_saved,
            datetime.fromtimestamp(cursor_ts / 1000).strftime("%Y-%m-%d %H:%M")))
        print("  批间随机等待 {}~{} 秒（下限 {} 秒，实际约 {:.1f}~{:.1f} 秒）".format(
            low, high, self.min_interval, eff, max(self.min_interval, high)))

        try:
            while True:
                if self.max_count and total_saved >= self.max_count:
                    print("已达到 max_count={}，停止".format(self.max_count))
                    break
                if reached_start:
                    print("已早于 start_date={}，停止".format(self.start_date))
                    break

                batch_no += 1
                time.sleep(random_interval(self.interval, self.min_interval))
                try:
                    text = self.client.search_tag(
                        self.tag, self.sort, self.batch_size, got_num, cursor_ts,
                        encoded=encoded_mode)
                    rate_limit_streak = 0
                except RateLimitedError:
                    rate_limit_streak += 1
                    if rate_limit_streak >= 5:
                        raise SystemExit("连续 5 次触发限流，建议增大 request_interval 后重试（进度已保存）")
                    print("触发限流，退避 {}s 后原地重试（进度未推进）".format(self.backoff))
                    time.sleep(self.backoff)
                    batch_no -= 1
                    continue

                posts = extract_posts(text, self.tag)
                if self.skip_img_posts:
                    posts = [p for p in posts if p.post_type != "img"]
                if self.debug_raw and (not posts or len(posts) < self.batch_size):
                    self._dump_raw(batch_no, text)

                # ---- 空批 ----
                if not posts:
                    if total_saved == 0 and not encoded_tried:
                        encoded_tried = True
                        encoded_mode = not encoded_mode
                        print("首批 0 条，切换 tag 参数编码形式为 {} 重试".format(
                            "URL编码" if encoded_mode else "原文"))
                        continue
                    if self.sort == "date":
                        if self.start_ts and cursor_ts <= self.start_ts:
                            reached_start = True
                            continue
                        empty_streak += 1
                        if empty_streak > self.empty_day_limit:
                            print("连续 {} 天没有更早的帖子，爬取完成".format(self.empty_day_limit))
                            break
                        cursor_ts -= DAY_MS
                        got_num = 0
                        if empty_streak % 7 == 0:
                            print("  已回溯到 {}（近 {} 天空窗）".format(
                                self._fmt_day(cursor_ts), empty_streak))
                        self._save_progress(self.sort, cursor_ts, got_num, oldest_ts,
                                            total_saved, encoded_mode, empty_streak, batch_no)
                        continue
                    print("已翻到末尾。new 排序平台单次上限约 1099 篇；"
                          "若要更早的文章，把 config 里 crawl.sort 改成 date（按天回溯，较慢）")
                    break

                new_posts = [p for p in posts if p.url not in seen]
                batch_min = min(p.publish_ts for p in posts)

                # ---- 整批都是旧帖：服务器重发了同一页，回退一天开新窗口 ----
                if not new_posts:
                    empty_streak += 1
                    if empty_streak > self.empty_day_limit:
                        print("连续多批没有新内容，爬取完成")
                        break
                    cursor_ts = min(cursor_ts, batch_min) - DAY_MS
                    got_num = 0
                    self._save_progress(self.sort, cursor_ts, got_num, oldest_ts,
                                        total_saved, encoded_mode, empty_streak, batch_no)
                    continue
                empty_streak = 0

                # ---- 落盘 ----
                if self.min_hot > 0:
                    new_posts = [p for p in new_posts if p.hot >= self.min_hot]
                if self.start_ts:
                    before = len(new_posts)
                    new_posts = [p for p in new_posts if p.publish_ts >= self.start_ts]
                    if len(new_posts) < before:
                        reached_start = True
                truncated = False
                if self.max_count and len(new_posts) > self.max_count - total_saved:
                    new_posts = new_posts[:self.max_count - total_saved]
                    truncated = True

                records = [p.to_dict() for p in new_posts]
                storage.append_jsonl(storage.POSTS_JSONL, records)
                if self.save_txt:
                    for p in new_posts:
                        try:
                            storage.save_txt_backup(p)
                        except OSError as e:
                            print("  txt 备份失败 {}: {}".format(p.url, e))
                seen.update(p.url for p in new_posts)
                total_saved += len(new_posts)

                if batch_min:
                    if truncated:
                        # 按配额截断过：游标只推进到最后保存的帖子，尾部下次续爬补回
                        cursor_ts = min(cursor_ts, new_posts[-1].publish_ts)
                    else:
                        cursor_ts = min(cursor_ts, batch_min)
                    oldest_ts = batch_min if oldest_ts is None else min(oldest_ts, batch_min)
                got_num += self.batch_size   # lofterSpider 惯例：按请求量累加

                self._save_progress(self.sort, cursor_ts, got_num, oldest_ts,
                                    total_saved, encoded_mode, empty_streak, batch_no)
                print("批次{:>3}：本批 {} 篇 / 新增 {} 篇 / 累计 {} 篇 / 最旧 {}".format(
                    batch_no, len(posts), len(new_posts), total_saved,
                    self._fmt_day(oldest_ts) if oldest_ts else "-"))
                if truncated:
                    print("已达到 max_count={}，停止".format(self.max_count))
                    break
        except KeyboardInterrupt:
            print("\n手动中断，进度已保存，重新运行 crawl 命令即可续爬")

        print("爬取结束：累计 {} 篇，数据在 {}".format(total_saved, storage.POSTS_JSONL))
        if 0 < total_saved < 20:
            print("提示：只爬到很少的几篇。如果这个 tag 明显不止这些，"
                  "把 config 里 crawl.sort 改成 new 重跑（当前 sort={}）；"
                  "若仍异常，把 data/posts/raw/ 里的原始响应文件发来分析。".format(self.sort))
        return total_saved


def random_interval(interval, floor=3.0):
    """批间随机间隔，下限 floor（Lofter 频控保护，可用 crawl.min_request_interval 调）。"""
    low, high = float(interval[0]), float(interval[1])
    if high < low:
        low, high = high, low
    return max(float(floor or 0), random.uniform(low, high))

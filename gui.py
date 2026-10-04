"""蒸馏工坊 GUI 启动器。

python gui.py                 # 桌面窗口（pywebview/Edge WebView2），失败自动回退浏览器
python gui.py --browser       # 强制浏览器模式
python gui.py --watch         # 前端热重载：常驻 vite build --watch，改源码自动重建、页面自动刷新

启动时自动保证前端是最新构建（frontend/src 比产物新就自动 npm run build）。
重复启动：同版本已在跑 -> 直接打开/聚焦；旧版本占端口 -> 自动结束并接管。
"""
import argparse
import atexit
import json
import os
import socket
import subprocess
import sys
import threading
import time

import webbrowser

from gui.server import SERVER_VERSION, app

ROOT = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT, "frontend")
DIST_INDEX = os.path.join(ROOT, "gui", "dist", "index.html")
NODE_MODULES = os.path.join(FRONTEND_DIR, "node_modules")
_watch_proc = None


def find_free_port(start, tries=20):
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"{start}~{start + tries - 1} 端口都被占用，用 --port 指定一个")


def frontend_is_stale():
    """前端源码比构建产物新（或产物缺失）时需要重建。"""
    if not os.path.isfile(DIST_INDEX):
        return True
    src = newest_mtime(os.path.join(FRONTEND_DIR, "src"))
    src = max(src, os.stat(os.path.join(FRONTEND_DIR, "index.html")).st_mtime,
              os.stat(os.path.join(FRONTEND_DIR, "vite.config.js")).st_mtime)
    return src > os.stat(DIST_INDEX).st_mtime


def newest_mtime(path):
    newest = 0
    for cur, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for f in files:
            try:
                newest = max(newest, os.stat(os.path.join(cur, f)).st_mtime)
            except OSError:
                continue
    return newest


def npm(args):
    return subprocess.run("npm " + args, shell=True, cwd=FRONTEND_DIR,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def ensure_frontend_built():
    """确保 dist 是最新构建；源码有改动时自动重建。"""
    if not frontend_is_stale():
        return
    if not os.path.isdir(NODE_MODULES):
        print("首次运行：安装前端依赖（npm install）…")
        r = npm("install")
        if r.returncode != 0:
            raise SystemExit("npm install 失败：\n" + (r.stderr or r.stdout)[-800:])
    print("前端有更新，自动重建（npm run build）…")
    r = npm("run build")
    if r.returncode != 0:
        raise SystemExit("npm run build 失败：\n" + (r.stderr or r.stdout)[-800:])
    print("前端构建完成。")


def probe_server(port):
    """探测端口上的服务：'current'=同版本本工具，'stale'=旧版本本工具，None=没有/别的程序。"""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if data.get("server_version") == SERVER_VERSION:
        return "current"
    if "config" in data and "running" in data:   # 本工具旧版的状态特征
        return "stale"
    return None


def kill_port_owner(port):
    ps = ("Get-NetTCPConnection -LocalPort {} -State Listen -ErrorAction SilentlyContinue | "
          "Select-Object -First 1 -ExpandProperty OwningProcess").format(port)
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True)
    pid = out.stdout.strip()
    if pid.isdigit():
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
        return True
    return False


def start_watch():
    """前端热重载：常驻 vite build --watch，源码一改自动重建 dist。"""
    global _watch_proc
    if not os.path.isdir(FRONTEND_DIR):
        print("  --watch：找不到 frontend/ 目录，跳过热重载")
        return
    try:
        _watch_proc = subprocess.Popen(
            "npm run watch", shell=True, cwd=FRONTEND_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(_watch_proc.terminate)
        print("  前端热重载已开启（vite build --watch 常驻）")
    except OSError as e:
        print("  --watch 启动失败：{}".format(e))


def warn_orphan_stages():
    """检测旧窗口遗留的阶段子进程：它们仍在跑，但进度不在本窗口显示。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*main.py*' } | "
          "Select-Object -ExpandProperty ProcessId")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True)
        pids = [p for p in out.stdout.split() if p.isdigit()]
    except OSError:
        return
    if pids:
        from gui.server import _append_log
        msg = ("检测到旧窗口遗留的阶段进程（PID {}）：它们仍在后台运行，"
               "数据照常写入，但进度不在本窗口显示；如需立即停止可手动结束这些进程。"
               .format("、".join(pids)))
        print(msg)
        _append_log(msg)


def serve_flask(port):
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


def open_desktop_window(port):
    """只开桌面窗口（Flask 由调用方负责启动）。"""
    import webview
    webview.create_window("蒸馏工坊", f"http://127.0.0.1:{port}",
                          width=1440, height=920, min_size=(1024, 640))
    webview.start()


def run_desktop(port):
    """桌面窗口模式：本进程起 Flask + 开窗口。"""
    threading.Thread(target=serve_flask, args=(port,), daemon=True).start()
    time.sleep(0.8)   # 等 Flask 就绪
    open_desktop_window(port)


def run_browser(port, open_browser=True):
    import webbrowser
    print(f"蒸馏工坊已启动：http://127.0.0.1:{port}（在浏览器中打开；Ctrl+C 退出）")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    serve_flask(port)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="蒸馏工坊 GUI")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开界面")
    ap.add_argument("--browser", action="store_true", help="强制浏览器模式（默认桌面窗口）")
    ap.add_argument("--watch", action="store_true",
                    help="前端热重载：常驻 vite build --watch，改 frontend/ 源码自动重建")
    args = ap.parse_args()

    # 同版本已在跑：直接打开桌面窗口；旧版本占端口：自动接管
    state = probe_server(args.port)
    if state == "current" and not args.watch:
        print(f"GUI 已在运行（http://127.0.0.1:{args.port}），直接打开界面")
        if args.browser:
            if not args.no_browser:
                webbrowser.open(f"http://127.0.0.1:{args.port}")
        else:
            open_desktop_window(args.port)   # 复用已在跑的后端，只开窗口
        return
    if state == "stale":
        print(f"发现旧版 GUI 占用端口 {args.port}，自动关闭旧进程…")
        if not kill_port_owner(args.port):
            raise SystemExit("旧进程关闭失败，请手动关闭后重新运行")
        time.sleep(1.5)

    ensure_frontend_built()

    if args.watch:
        start_watch()

    use_desktop = not args.browser
    if use_desktop:
        try:
            import webview   # noqa: F401
        except ImportError:
            use_desktop = False
            print("pywebview 未安装（pip install pywebview），回退浏览器模式")

    # 孤儿进程检测放后台跑：powershell 冷启动要几秒，不能拖慢界面启动
    threading.Thread(target=warn_orphan_stages, daemon=True).start()

    if use_desktop:
        run_desktop(args.port)
    else:
        run_browser(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()

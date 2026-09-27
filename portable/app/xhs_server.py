#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
小红书笔记统计台 · 本地服务（便携版）
=====================================================
接口一览：
    GET  /                     工作台页面
    GET  /api/status           运行状态（飞书登录 / Cookie / 统计）
    GET  /api/notes            本地笔记列表
    POST /api/fetch            抓取一条笔记（存本地 + 同步飞书）
    POST /api/sync             把未同步的记录批量推送到飞书
    POST /api/delete           删除一条本地记录
    POST /api/settings         保存 Cookie / 表格配置
    POST /api/app/init/start   发起飞书官方"创建/绑定我的应用"向导
    POST /api/app/init/check   轮询应用是否已配置成功
    POST /api/app/bind         手动填入自己的 App ID / App Secret
    POST /api/app/reset        解除应用绑定（换用另一个应用）
    POST /api/setup            在登录账号自己的空间里新建飞书表格
    POST /api/reset            清空本地表格坐标（换账号时用）
    POST /api/login/start      发起飞书登录
    POST /api/login/finish     完成飞书登录
    GET  /api/img?u=           图片代理（绕过小红书防盗链）
    GET  /api/export?format=   导出 csv / json
"""
import os
import sys
import json
import time
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 控制台编码：沿用系统默认（中文 Windows 即 cp936），与 bat 的 GBK 保持一致；
# 仅追加容错，避免个别字符编码失败导致输出中断。
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import xhs_core          # noqa: E402
import feishu            # noqa: E402
import store             # noqa: E402

WEB_DIR = os.path.join(HERE, "web")
HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("XHS_PORT", "8787"))

_lock = threading.Lock()


# ---------------------------------------------------------------- 工具
def pick_port(start):
    for p in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((HOST, p))
                return p
            except OSError:
                continue
    return start


def to_int(v):
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except Exception:
        return 0


def stats_of(notes):
    liked = sum(to_int(n.get("liked")) for n in notes)
    collected = sum(to_int(n.get("collected")) for n in notes)
    comment = sum(to_int(n.get("comment")) for n in notes)
    dist = {}
    for n in notes:
        t = n.get("type") or "其他"
        dist[t] = dist.get(t, 0) + 1
    return {
        "total": len(notes),
        "liked": liked,
        "collected": collected,
        "comment": comment,
        "pending": sum(1 for n in notes if not n.get("synced")),
        "types": dist,
    }


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "XHSWorkbench/2.0"

    def log_message(self, fmt, *args):
        pass

    # ---- 响应 ----
    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, data, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p in ("/", "/index.html"):
            fp = os.path.join(WEB_DIR, "index.html")
            if not os.path.exists(fp):
                return self._json({"ok": False, "error": "页面文件缺失"}, 500)
            with open(fp, "rb") as f:
                return self._bytes(f.read(), "text/html; charset=utf-8")

        if p == "/api/status":
            notes = store.load_notes()
            st = feishu.load_settings()
            ck = xhs_core.load_cookie()
            app = feishu.app_config()
            fs = feishu.auth_status()
            provisioned = bool(st.get("base_token") and st.get("table_id"))
            logged_in = fs.get("logged_in", False)
            app_ready = bool(app.get("configured"))
            # 四步：① 绑定自己的飞书应用 ② 登录 ③ 建表 ④ 配置小红书 Cookie
            steps = {
                "app": app_ready,
                "login": logged_in,
                "base": provisioned,
                "cookie": bool(ck),
            }
            return self._json({
                "ok": True,
                "app": app,
                "steps": steps,
                "ready": all(steps.values()),
                "feishu": {
                    "logged_in": logged_in,
                    "user": fs.get("user", ""),
                    "base_url": st.get("base_url", ""),
                    "base_token": st.get("base_token", ""),
                    "table_id": st.get("table_id", ""),
                    "error": fs.get("error", ""),
                    "provisioned": provisioned,
                    "needs_setup": bool(app_ready and logged_in and not provisioned),
                },
                "cookie": {"configured": bool(ck), "length": len(ck)},
                "stats": stats_of(notes),
            })

        if p == "/api/notes":
            notes = store.load_notes()
            return self._json({"ok": True, "notes": notes, "stats": stats_of(notes)})

        if p == "/api/img":
            url = (q.get("u") or [""])[0]
            if not url.startswith("http"):
                return self._json({"ok": False, "error": "bad url"}, 400)
            try:
                code, ctype, blob = xhs_core.http_get_bytes(
                    url, headers={"User-Agent": xhs_core.UA,
                                  "Referer": "https://www.xiaohongshu.com/"})
                return self._bytes(blob, ctype, code if code == 200 else 502)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 502)

        if p == "/api/export":
            fmt = (q.get("format") or ["json"])[0].lower()
            notes = store.load_notes()
            if fmt == "csv":
                data = store.to_csv(notes).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="xhs_notes.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
            data = json.dumps(notes, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition",
                             'attachment; filename="xhs_notes.json"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)

        return self._json({"ok": False, "error": "not found"}, 404)

    # ---- POST ----
    def do_POST(self):
        p = urlparse(self.path).path
        body = self._body()

        if p == "/api/fetch":
            return self._fetch(body)
        if p == "/api/sync":
            return self._sync()
        if p == "/api/delete":
            with _lock:
                ok = store.delete_note((body.get("note_id") or "").strip())
            return self._json({"ok": ok})
        if p == "/api/settings":
            return self._settings(body)
        if p == "/api/app/init/start":
            return self._app_init_start()
        if p == "/api/app/init/check":
            return self._json({"ok": True, "app": feishu.app_init_status()})
        if p == "/api/app/bind":
            return self._app_bind(body)
        if p == "/api/app/reset":
            # 换应用后原来的表格坐标不再适用，一并清空
            feishu.reset_settings()
            return self._json({"ok": True, "app": feishu.app_reset()})
        if p == "/api/setup":
            return self._setup(body)
        if p == "/api/reset":
            feishu.reset_settings()
            return self._json({"ok": True, "feishu": feishu.load_settings()})
        if p == "/api/login/start":
            return self._login_start()
        if p == "/api/login/finish":
            return self._login_finish(body)

        return self._json({"ok": False, "error": "not found"}, 404)

    # ---- 业务 ----
    def _fetch(self, body):
        from xhs_core import XHSError
        raw = (body.get("url") or "").strip()
        if not raw:
            return self._json({"ok": False, "error": "缺少链接"})

        try:
            info = xhs_core.fetch_note(raw, xhs_core.load_cookie())
        except XHSError as e:
            return self._json({"ok": False, "error": str(e), "kind": "fetch"})
        except Exception as e:
            return self._json({"ok": False, "error": f"抓取出错：{e}", "kind": "fetch"})

        # 先落本地，保证离线不丢数据
        with _lock:
            action, _ = store.upsert_local(info, synced=False)

        # 再尝试同步飞书
        sync = {"synced": False, "message": ""}
        app_ok = feishu.app_config().get("configured")
        fs = feishu.auth_status()
        if not app_ok:
            sync["message"] = "尚未绑定飞书应用，已存本地（完成首次设置后可同步）"
        elif not fs.get("logged_in"):
            sync["message"] = "飞书未登录，已存本地（登录后可一键同步）"
        elif not feishu.is_provisioned():
            sync["message"] = "尚未创建飞书表格，已存本地（在设置里点「创建我的表格」）"
        else:
            try:
                act, rid = feishu.upsert_note(info)
                with _lock:
                    store.mark_synced(info["note_id"], rid)
                sync = {"synced": True, "message": f"已{'更新' if act == 'updated' else '写入'}飞书"}
            except Exception as e:
                sync["message"] = f"飞书同步失败：{str(e)[:150]}"

        notes = store.load_notes()
        return self._json({"ok": True, "note": info, "action": action,
                           "sync": sync, "stats": stats_of(notes)})

    def _sync(self):
        if not feishu.app_config().get("configured"):
            return self._json({"ok": False, "error": "尚未绑定飞书应用，请先在「首次使用」里完成第 1 步"})
        fs = feishu.auth_status()
        if not fs.get("logged_in"):
            return self._json({"ok": False, "error": "飞书未登录，请先登录"})
        if not feishu.is_provisioned():
            return self._json({"ok": False, "error": "尚未创建飞书表格，请先在设置里点「创建我的表格」"})
        notes = store.load_notes()
        pending = [n for n in notes if not n.get("synced")]
        if not pending:
            return self._json({"ok": True, "synced": 0, "message": "没有待同步的记录"})

        ok, fail = 0, 0
        last_err = ""
        for n in pending:
            try:
                act, rid = feishu.upsert_note(n)
                with _lock:
                    store.mark_synced(n["note_id"], rid)
                ok += 1
            except Exception as e:
                fail += 1
                last_err = str(e)[:150]
            time.sleep(0.4)
        msg = f"同步完成：成功 {ok} 条" + (f"，失败 {fail} 条（{last_err}）" if fail else "")
        return self._json({"ok": True, "synced": ok, "failed": fail, "message": msg})

    def _settings(self, body):
        if "cookie" in body:
            xhs_core.save_cookie(body.get("cookie") or "")
        conf = {}
        for k in ("base_token", "table_id", "base_url"):
            if body.get(k):
                conf[k] = str(body[k]).strip()
        if conf:
            feishu.save_settings(conf)
        ck = xhs_core.load_cookie()
        return self._json({"ok": True, "cookie": {"configured": bool(ck), "length": len(ck)}})

    def _app_init_start(self):
        """走飞书官方向导，为使用者创建/绑定属于他自己的飞书应用"""
        try:
            return self._json({"ok": True, **feishu.app_init_start()})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)})

    def _app_bind(self, body):
        """使用者手动填入自己的 App ID / App Secret"""
        try:
            cfg = feishu.app_bind(body.get("app_id"), body.get("app_secret"),
                                  body.get("brand") or "feishu")
            return self._json({"ok": True, "app": cfg})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:300]})

    def _setup(self, body):
        """在登录账号自己的飞书空间里新建一张表格"""
        if not feishu.app_config().get("configured"):
            return self._json({"ok": False, "error": "还没有绑定飞书应用，请先完成第 1 步"})
        fs = feishu.auth_status()
        if not fs.get("logged_in"):
            return self._json({"ok": False, "error": "请先登录飞书，登录后才能创建表格"})
        if feishu.is_provisioned() and not body.get("force"):
            return self._json({"ok": True, "feishu": feishu.load_settings(), "reused": True})
        try:
            st = feishu.provision_base()
            return self._json({"ok": True, "feishu": st, "created": True})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)[:300]})

    def _login_start(self):
        try:
            r = feishu.login_start()
            return self._json({"ok": True, **r})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)})

    def _login_finish(self, body):
        try:
            st = feishu.login_finish(body.get("device_code"))
            return self._json({"ok": True, "feishu": st})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)})


def main():
    port = pick_port(DEFAULT_PORT)
    url = f"http://{HOST}:{port}"
    srv = ThreadingHTTPServer((HOST, port), Handler)

    print("=" * 52)
    print("  小红书笔记统计台 · 已启动")
    print(f"  访问地址：{url}")
    print(f"  工作目录：{ROOT}")
    ck = xhs_core.load_cookie()
    st = feishu.load_settings()
    print(f"  Cookie  ：{'已配置' if ck else '未配置（请在页面设置中填写）'}")
    app = feishu.app_config()
    print(f"  飞书应用：{app.get('app_id') if app.get('configured') else '未绑定（首次使用请在工作台完成第 1 步）'}")
    print(f"  飞书表格：{st['base_url'] if st.get('base_url') else '未创建（登录后点「创建我的表格」）'}")
    print("  关闭窗口或按 Ctrl+C 停止服务")
    print("=" * 52)

    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()

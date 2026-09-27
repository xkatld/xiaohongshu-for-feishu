# -*- coding: utf-8 -*-
"""
小红书统计工作流 - 本地服务
=====================================================
提供工作台页面与接口：
    GET  /            工作台页面
    GET  /api/notes   读取飞书多维表格中的全部笔记
    POST /api/fetch   抓取单条笔记并写入飞书
    GET  /api/img?u=  图片代理（绕过小红书防盗链）

启动：python xhs_server.py  → 浏览器打开 http://127.0.0.1:8787
"""
import os
import io
import sys
import json
import tempfile
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xhs_workflow as wf                                    # noqa: E402
from xhs_core import fetch_note, get_cookie_from_env, XHSError, UA  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML_PATH = os.path.join(ROOT, "workbench.html")
HOST = "127.0.0.1"
PORT = int(os.environ.get("XHS_PORT", "8787"))
MAX_BATCH = 200


# ---------------------------------------------------------------- 飞书读取
def list_records():
    path = wf.tmp_path("records_", ".ndjson")
    try:
        res = wf._run_lark([
            "base", "+record-list",
            "--base-token", wf.BASE_TOKEN,
            "--table-id", wf.TABLE_ID,
            "--limit", "2000",
            "--format", "ndjson",
            "--output", path,
            "--as", "user",
        ], timeout=90)
        # 失败时返回 {"ok": false, "error": {...}}；成功时返回 manifest（无 ok 字段）
        if isinstance(res, dict) and res.get("ok") is False:
            raise RuntimeError(json.dumps(res.get("error"), ensure_ascii=False))
        out_path = (res.get("record_file") if isinstance(res, dict) else None) or path
        if not os.path.exists(out_path):
            raise RuntimeError(f"未生成记录文件：{out_path}")
        rows = []
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------- 图片代理
def proxy_image(url):
    headers = {"User-Agent": UA, "Referer": "https://www.xiaohongshu.com/", "Accept": "image/*,*/*"}
    r = requests.get(url, headers=headers, timeout=20)
    ctype = r.headers.get("Content-Type", "image/jpeg")
    return r.status_code, ctype, r.content


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "XHSWorkflow/1.0"

    def log_message(self, fmt, *args):
        pass  # 静默

    # ---- 响应工具 ----
    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, data, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    # ---- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)

        if p in ("/", "/index.html"):
            if not os.path.exists(HTML_PATH):
                return self._json({"ok": False, "error": "workbench.html 不存在"}, 500)
            with open(HTML_PATH, "rb") as f:
                return self._bytes(f.read(), "text/html; charset=utf-8")

        if p == "/api/notes":
            try:
                rows = list_records()
                return self._json({"ok": True, "notes": rows, "total": len(rows)})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})

        if p == "/api/img":
            url = (q.get("u") or [""])[0]
            if not url.startswith("http"):
                return self._json({"ok": False, "error": "bad url"}, 400)
            try:
                code, ctype, blob = proxy_image(url)
                return self._bytes(blob, ctype)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 502)

        if p == "/api/health":
            return self._json({"ok": True, "service": "xhs-workflow", "port": PORT})

        return self._json({"ok": False, "error": "not found"}, 404)

    # ---- POST ----
    def do_POST(self):
        p = urlparse(self.path).path
        if p != "/api/fetch":
            return self._json({"ok": False, "error": "not found"}, 404)

        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json({"ok": False, "error": "请求体不是合法 JSON"}, 400)

        raw = (body.get("url") or "").strip()
        if not raw:
            return self._json({"ok": False, "error": "缺少参数 url"}, 400)

        cookie = get_cookie_from_env()
        if not cookie:
            return self._json({"ok": False, "error": "未配置 cookie（请写入 cookies/xhs_cookie.txt）"})

        try:
            info = fetch_note(raw, cookie)
        except XHSError as e:
            return self._json({"ok": False, "error": f"抓取失败：{e}"})
        except Exception as e:
            return self._json({"ok": False, "error": f"抓取出错：{e}"})

        # 去重：同一 note_id 已存在则只更新
        try:
            existing = list_records()
            dup = next((r for r in existing if r.get("note_id") == info["note_id"]), None)
            record = wf.build_record(info)
            if dup and dup.get("record_id"):
                res = wf._run_lark([
                    "base", "+record-batch-update",
                    "--base-token", wf.BASE_TOKEN,
                    "--table-id", wf.TABLE_ID,
                    "--json", json.dumps({"update_records": {dup["record_id"]: record}}, ensure_ascii=False),
                    "--as", "user",
                ])
                if not res.get("ok"):
                    raise RuntimeError(json.dumps(res.get("error"), ensure_ascii=False))
                return self._json({"ok": True, "note": info, "record_id": dup["record_id"], "action": "updated"})

            ids = wf.push_to_feishu([record])
            rid = ids[0] if ids else ""
            return self._json({"ok": True, "note": info, "record_id": rid, "action": "created"})
        except Exception as e:
            return self._json({"ok": False, "error": f"写入飞书失败:{e}"})


def main():
    if not os.path.exists(HTML_PATH):
        print(f"!! 未找到页面文件: {HTML_PATH}")
    cookie = get_cookie_from_env()
    print("=" * 56)
    print("  小红书笔记统计台 已启动")
    print(f"  访问地址 : http://{HOST}:{PORT}")
    print(f"  飞书表格 : {wf.BASE_URL}")
    print(f"  Cookie   : {'已配置' if cookie else '未配置（抓取会失败）'}")
    print("  停止服务 : Ctrl + C")
    print("=" * 56)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        srv.shutdown()


if __name__ == "__main__":
    main()

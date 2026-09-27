# -*- coding: utf-8 -*-
"""
小红书笔记抓取核心模块（零第三方依赖，仅用 Python 标准库）
--------------------------------------------------
输入：小红书分享链接 / 分享文案 / note_id
输出：结构化笔记数据 dict

原理：携带 Cookie 请求笔记详情页 HTML，解析 window.__INITIAL_STATE__ 中的
     note.noteDetailMap[note_id].note 数据。
"""
import os
import re
import json
import time
import gzip
import zlib
import ssl
import urllib.request
import urllib.error

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

NOTE_ID_RE = re.compile(r"(?:item|explore|discovery/item)/([0-9a-fA-F]{24})")
URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff，。、]+")
XHS_HOSTS = ("xiaohongshu.com", "xhslink.com")

# 便携包根目录（app/ 的上一级）；同时兼容开发期 scripts/ 结构
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _ssl_context():
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        # 某些精简环境缺少系统根证书，降级为不校验（仅影响可用性，不影响功能）
        ctx = ssl._create_unverified_context()
    return ctx


_SSL_CTX = None


def _ctx():
    global _SSL_CTX
    if _SSL_CTX is None:
        _SSL_CTX = _ssl_context()
    return _SSL_CTX


class XHSError(Exception):
    pass


# ---------------------------------------------------------------- HTTP（标准库）
def http_get(url, headers=None, timeout=25, max_redirect=10):
    """极简 GET，返回 (status, final_url, text)"""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
            raw = resp.read()
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            if "gzip" in enc:
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            elif "deflate" in enc:
                try:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    pass
            ctype = resp.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w\-]+)", ctype)
            charset = m.group(1) if m else "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return resp.status, resp.geturl(), text
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        return e.code, url, body.decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise XHSError(f"网络请求失败：{e.reason}")


def http_get_bytes(url, headers=None, timeout=25):
    """下载二进制（用于图片代理）"""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
            return resp.status, resp.headers.get("Content-Type", "image/jpeg"), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, "text/plain", str(e).encode()
    except urllib.error.URLError as e:
        raise XHSError(f"图片下载失败：{e.reason}")


# ---------------------------------------------------------------- 链接解析
def extract_share_url(text):
    """从任意分享文案里抠出小红书链接"""
    if not text:
        raise XHSError("分享内容为空")
    text = text.strip()
    if text.startswith("http") and " " not in text:
        return text
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip("，。、)）】]")
        if any(h in u for h in XHS_HOSTS):
            return u
    raise XHSError("未在文本中找到小红书链接")


def parse_note_id(url):
    m = NOTE_ID_RE.search(url)
    if m:
        return m.group(1)
    m = re.search(r"/([0-9a-fA-F]{24})(?:\?|$)", url)
    if m:
        return m.group(1)
    raise XHSError(f"无法从链接解析 note_id: {url}")


def parse_xsec_token(url):
    m = re.search(r"[?&]xsec_token=([^&\s]+)", url)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- HTML / JSON 解析
def _close_balanced(text, open_idx, oc="{", cc="}"):
    depth, in_str, esc = 0, False, False
    for j in range(open_idx, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == oc:
                depth += 1
            elif ch == cc:
                depth -= 1
                if depth == 0:
                    return j
    return None


def _strip_js_constructors(s):
    """把 new Map(...) / new Set(...) 这类非 JSON 表达式替换为 {}"""
    for ctor in ("new Map(", "new Set("):
        guard = 0
        while guard < 500:
            guard += 1
            i = s.find(ctor)
            if i < 0:
                break
            op = i + len(ctor) - 1
            end = _close_balanced(s, op, "(", ")")
            if end is None:
                break
            s = s[:i] + "{}" + s[end + 1:]
    return s


def parse_initial_state(html):
    key = "window.__INITIAL_STATE__="
    idx = html.find(key)
    if idx < 0:
        raise XHSError("页面中未找到 __INITIAL_STATE__（Cookie 可能失效，或需要滑块验证）")
    brace = html.find("{", idx)
    end = _close_balanced(html, brace)
    if end is None:
        raise XHSError("__INITIAL_STATE__ 结构异常，无法解析")
    js = html[brace:end + 1]
    js = _strip_js_constructors(js)
    js = re.sub(r"\bundefined\b", "null", js)
    js = re.sub(r"\bNaN\b", "null", js)
    try:
        return json.loads(js)
    except json.JSONDecodeError as e:
        raise XHSError(f"页面数据 JSON 解析失败：{e}")


# ---------------------------------------------------------------- 数据抽取
def _pick_cover(note):
    imgs = note.get("imageList") or []
    if imgs:
        first = imgs[0]
        return first.get("urlDefault") or first.get("url") or ""
    return ""


def extract_note(data, note_id):
    note_map = (data.get("note") or {}).get("noteDetailMap") or {}
    if not note_map:
        raise XHSError("页面数据中没有笔记内容（Cookie 失效、笔记被删或权限受限）")
    entry = note_map.get(note_id) or next(iter(note_map.values()))
    note = entry.get("note") or {}
    if not note:
        raise XHSError("笔记数据结构异常")

    tags = [t.get("name") for t in (note.get("tagList") or []) if t.get("name")]
    interact = note.get("interactInfo") or {}
    user = note.get("user") or {}
    imgs = note.get("imageList") or []

    all_images = []
    for im in imgs:
        u = im.get("urlDefault") or im.get("url")
        if u:
            all_images.append(u)

    ts = note.get("time")
    publish_time = ""
    if ts:
        try:
            publish_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts) / 1000))
        except Exception:
            publish_time = ""

    return {
        "note_id": note.get("noteId") or note_id,
        "title": (note.get("title") or "").strip(),
        "desc": (note.get("desc") or "").strip(),
        "tags": tags,
        "tags_text": " ".join(f"#{t}" for t in tags),
        "type": "视频" if note.get("type") == "video" else "图文",
        "images": all_images,
        "cover": _pick_cover(note),
        "author": user.get("nickname") or "",
        "author_id": user.get("userId") or "",
        "liked": interact.get("likedCount") or "0",
        "collected": interact.get("collectedCount") or "0",
        "comment": interact.get("commentCount") or "0",
        "share": interact.get("shareCount") or "0",
        "publish_time": publish_time,
        "ip_location": note.get("ipLocation") or "",
        "url": "",
    }


def _to_int(v):
    try:
        return int(v)
    except Exception:
        return 0


# ---------------------------------------------------------------- Cookie 读取
def cookie_path():
    for name in ("config", "cookies"):
        p = os.path.join(ROOT, name, "xhs_cookie.txt")
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, "config", "xhs_cookie.txt")


def load_cookie():
    p = cookie_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    return ""


def save_cookie(text):
    p = cookie_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write((text or "").strip())
    return p


# ---------------------------------------------------------------- 对外主函数
def fetch_note(share_text_or_url, cookie, timeout=25):
    """抓取单条小红书笔记，返回结构化 dict"""
    if not cookie:
        raise XHSError("未配置小红书 Cookie（请在页面「设置」中填写）")

    raw_url = extract_share_url(share_text_or_url)
    if "xhslink.com" in raw_url:
        _, raw_url, _ = http_get(raw_url, headers={"User-Agent": UA}, timeout=timeout)

    note_id = parse_note_id(raw_url)
    token = parse_xsec_token(raw_url)

    if token:
        fetch_url = (f"https://www.xiaohongshu.com/explore/{note_id}"
                     f"?xsec_token={token}&xsec_source=pc_share")
    else:
        fetch_url = f"https://www.xiaohongshu.com/explore/{note_id}"

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.xiaohongshu.com/",
        "Cookie": (cookie or "").strip(),
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }
    status, _, html = http_get(fetch_url, headers=headers, timeout=timeout)
    if status != 200:
        raise XHSError(f"请求失败 HTTP {status}")

    data = parse_initial_state(html)
    info = extract_note(data, note_id)

    info["url"] = f"https://www.xiaohongshu.com/explore/{note_id}"
    for k in ("liked", "collected", "comment", "share"):
        info[k] = _to_int(info[k])
    info["fetch_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return info

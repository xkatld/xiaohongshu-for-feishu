# -*- coding: utf-8 -*-
"""
小红书笔记抓取核心模块
--------------------------------------------------
输入：小红书分享链接 / 分享文案 / 纯 note_id
输出：结构化笔记数据 dict

原理：带 cookie 请求笔记详情页 HTML，解析 window.__INITIAL_STATE__ 中的
     note.noteDetailMap[note_id].note 数据。
"""
import re
import json
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

NOTE_ID_RE = re.compile(r"(?:item|explore|discovery/item)/([0-9a-fA-F]{24})")
URL_RE = re.compile(r"https?://[^\s\u4e00-\u9fff，。、]+")
XHS_HOSTS = ("xiaohongshu.com", "xhslink.com")


class XHSError(Exception):
    pass


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


def resolve_short_url(url, session):
    """xhslink.com 短链 -> 展开成完整链接"""
    if "xhslink.com" not in url:
        return url
    r = session.get(url, headers={"User-Agent": UA}, allow_redirects=True, timeout=20)
    return r.url


# ---------------------------------------------------------------- HTML 解析
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
        raise XHSError("页面中未找到 __INITIAL_STATE__（cookie 可能失效或需要滑块验证）")
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
        raise XHSError(f"页面数据 JSON 解析失败: {e}")


# ---------------------------------------------------------------- 数据抽取
def _pick_cover(note):
    """取第一张图/封面"""
    imgs = note.get("imageList") or []
    if imgs:
        first = imgs[0]
        return first.get("urlDefault") or first.get("url") or ""
    return ""


def extract_note(data, note_id):
    note_map = (data.get("note") or {}).get("noteDetailMap") or {}
    if not note_map:
        raise XHSError("页面数据中没有笔记内容（cookie 失效、笔记被删或权限受限）")
    entry = note_map.get(note_id)
    if entry is None:
        entry = next(iter(note_map.values()))
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


# ---------------------------------------------------------------- 对外主函数
def fetch_note(share_text_or_url, cookie, timeout=25):
    """
    抓取单条小红书笔记。
    :param share_text_or_url: 分享文案 / 链接 / note_id
    :param cookie: 小红书登录 cookie 字符串
    :return: dict
    """
    session = requests.Session()
    raw_url = extract_share_url(share_text_or_url)
    url = resolve_short_url(raw_url, session)
    note_id = parse_note_id(url)
    token = parse_xsec_token(url)

    if token:
        fetch_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_share"
    else:
        fetch_url = f"https://www.xiaohongshu.com/explore/{note_id}"

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.xiaohongshu.com/",
        "Cookie": cookie.strip(),
        "Upgrade-Insecure-Requests": "1",
    }
    r = session.get(fetch_url, headers=headers, timeout=timeout)
    if r.status_code != 200:
        raise XHSError(f"请求失败 HTTP {r.status_code}")

    data = parse_initial_state(r.text)
    info = extract_note(data, note_id)

    info["url"] = f"https://www.xiaohongshu.com/explore/{note_id}"
    info["liked"] = _to_int(info["liked"])
    info["collected"] = _to_int(info["collected"])
    info["comment"] = _to_int(info["comment"])
    info["share"] = _to_int(info["share"])
    info["fetch_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return info


def get_cookie_from_env(default_cookie=""):
    """从 cookies/xhs_cookie.txt 读取 cookie，方便复用"""
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "cookies", "xhs_cookie.txt")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            c = f.read().strip()
            if c:
                return c
    return default_cookie


if __name__ == "__main__":
    import sys
    ck = get_cookie_from_env()
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = ("54 【这棵树到底结了多少苹果？ - 小九探秘 | 小红书 - 你的生活兴趣社区】 😆 LwO7RdlpBW92tVD 😆 "
                  "https://www.xiaohongshu.com/discovery/item/6a9d7ef9000000002b013bdb?source=webshare&xhsshare=pc_web"
                  "&xsec_token=ABk_3AeD7lWQQxMP3aKKHI4wezJIBoN6XSfHvkOW4XI5E=&xsec_source=pc_share")
    print(json.dumps(fetch_note(target, ck), ensure_ascii=False, indent=2))

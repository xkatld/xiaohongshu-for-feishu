# -*- coding: utf-8 -*-
"""
飞书多维表格操作层
--------------------------------------------------
通过便携包内置的 lark-cli（tools/lark-cli.exe）完成：
  · 登录状态检查 / Device Flow 扫码登录
  · 读取多维表格记录
  · 新增 / 更新记录（按 note_id 去重）

所有调用均为本地子进程，不做任何第三方依赖。
"""
import os
import json
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP_DIR = os.path.join(ROOT, "data", "_tmp")

DEFAULT_SETTINGS = {
    "base_token": "S6IGbRWTeaualFsWEkBc81zBn0g",
    "table_id": "tbl1c8KxkRxC2hCk",
    "base_url": "https://my.feishu.cn/base/S6IGbRWTeaualFsWEkBc81zBn0g",
}


class FeishuError(Exception):
    pass


# ---------------------------------------------------------------- 基础
def cli_path():
    for name in ("lark-cli.exe", "lark-cli"):
        p = os.path.join(ROOT, "tools", name)
        if os.path.exists(p):
            return p
    return "lark-cli"


def settings_path():
    return os.path.join(ROOT, "config", "settings.json")


def load_settings():
    s = dict(DEFAULT_SETTINGS)
    p = settings_path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                s.update(json.load(f) or {})
        except Exception:
            pass
    return s


def save_settings(d):
    s = load_settings()
    s.update(d or {})
    p = settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    return s


def tmp_file(prefix, suffix):
    os.makedirs(TMP_DIR, exist_ok=True)
    import time
    return os.path.join(TMP_DIR, f"{prefix}{int(time.time() * 1000)}{suffix}").replace("\\", "/")


def run(args, timeout=120):
    """执行 lark-cli，返回解析后的 dict"""
    exe = cli_path()
    try:
        proc = subprocess.run(
            [exe] + args,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    except FileNotFoundError:
        raise FeishuError("未找到 lark-cli，请确认 tools/lark-cli.exe 存在")
    except subprocess.TimeoutExpired:
        raise FeishuError("lark-cli 执行超时")

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if not out:
        if err:
            raise FeishuError(err[:300])
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # 输出可能混有日志行，取最后一个完整 JSON 对象
        start = out.find("{")
        end = out.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(out[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise FeishuError(f"lark-cli 返回无法解析：{out[:200]}")


# ---------------------------------------------------------------- 登录
def auth_status():
    """返回 {logged_in, user, appId}"""
    try:
        res = run(["auth", "status"], timeout=60)
    except FeishuError as e:
        return {"logged_in": False, "error": str(e)}
    user = ((res.get("identities") or {}).get("user") or {})
    ok = bool(user.get("available")) and user.get("tokenStatus") == "valid"
    return {
        "logged_in": ok,
        "user": user.get("userName") or "",
        "open_id": user.get("openId") or "",
        "app_id": res.get("appId") or "",
        "status": user.get("status") or "",
    }


def login_start(domains="base,docs,drive"):
    """发起 Device Flow 登录，返回验证链接与设备码"""
    res = run(["auth", "login", "--no-wait", "--json", "--domain", domains], timeout=90)
    url = res.get("verification_url") or ""
    code = res.get("device_code") or ""
    if not url or not code:
        raise FeishuError(f"发起登录失败：{json.dumps(res, ensure_ascii=False)[:200]}")
    return {"verification_url": url, "device_code": code, "expires_in": res.get("expires_in") or 600}


def login_finish(device_code):
    """用户授权完成后调用，完成认证"""
    if not device_code:
        raise FeishuError("缺少 device_code")
    res = run(["auth", "login", "--device-code", device_code], timeout=120)
    st = auth_status()
    if not st.get("logged_in"):
        msg = res.get("raw") if isinstance(res, dict) and res.get("raw") else json.dumps(res, ensure_ascii=False)
        raise FeishuError(f"授权未完成或已过期：{str(msg)[:200]}")
    return st


# ---------------------------------------------------------------- 读写记录
def list_records():
    """读取全部记录（status 由 note_id 判断不存在时仍返回）"""
    st = load_settings()
    path = tmp_file("records_", ".ndjson")
    res = run([
        "base", "+record-list",
        "--base-token", st["base_token"],
        "--table-id", st["table_id"],
        "--limit", "2000",
        "--format", "ndjson",
        "--output", path,
        "--as", "user",
    ], timeout=180)

    if isinstance(res, dict) and res.get("ok") is False:
        raise FeishuError(json.dumps(res.get("error"), ensure_ascii=False))

    out_path = (res.get("record_file") if isinstance(res, dict) else None) or path
    if not os.path.exists(out_path):
        return []
    rows = []
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    try:
        os.remove(out_path)
    except OSError:
        pass
    return rows


def create_records(records):
    """批量新增，返回 record_id 列表"""
    if not records:
        return []
    st = load_settings()
    path = tmp_file("xhs_", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"create_records": records}, f, ensure_ascii=False)
    try:
        res = run([
            "base", "+record-batch-create",
            "--base-token", st["base_token"],
            "--table-id", st["table_id"],
            "--json", "@" + path,
            "--as", "user",
        ], timeout=120)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not res.get("ok"):
        raise FeishuError(json.dumps(res.get("error"), ensure_ascii=False))
    data = res.get("data") or {}
    return data.get("record_id_list") or []


def update_record(record_id, record):
    st = load_settings()
    payload = {"update_records": {record_id: record}}
    path = tmp_file("upd_", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    try:
        res = run([
            "base", "+record-batch-update",
            "--base-token", st["base_token"],
            "--table-id", st["table_id"],
            "--json", "@" + path,
            "--as", "user",
        ], timeout=120)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not res.get("ok"):
        raise FeishuError(json.dumps(res.get("error"), ensure_ascii=False))
    return True


# ---------------------------------------------------------------- 业务映射
def build_record(info):
    """抓取结果 -> 飞书多维表格记录"""
    return {
        "笔记标题": info["title"] or "（无标题）",
        "笔记类型": [info["type"]],
        "作者": info["author"],
        "标签": info["tags_text"],
        "正文": info["desc"],
        "图片链接": "\n".join(info["images"]),
        "点赞数": info["liked"],
        "收藏数": info["collected"],
        "评论数": info["comment"],
        "分享数": info["share"],
        "发布时间": info["publish_time"] or None,
        "笔记链接": info["url"],
        "note_id": info["note_id"],
        "抓取时间": info["fetch_time"],
    }


def upsert_note(info):
    """
    按 note_id 写入；已存在则更新。
    返回 (action, record_id)：action ∈ {created, updated}
    """
    existing = list_records()
    dup = next((r for r in existing if r.get("note_id") == info["note_id"]), None)
    record = build_record(info)
    if dup and dup.get("record_id"):
        update_record(dup["record_id"], record)
        return "updated", dup["record_id"]
    ids = create_records([record])
    return "created", (ids[0] if ids else "")

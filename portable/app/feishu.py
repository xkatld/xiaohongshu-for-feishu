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

# 表格坐标一律为空，必须由当前登录账号自己创建后再写入本地配置。
# 绝不内置任何人的表格地址，避免换账号后越权访问别人的文档。
DEFAULT_SETTINGS = {
    "base_token": "",
    "table_id": "",
    "base_url": "",
}

# 自动建表时使用的名称
BASE_NAME = "小红书笔记统计"
TABLE_NAME = "笔记"

# 表格字段结构，第一项为主字段；与 build_record() 的键一一对应
FIELD_SCHEMA = [
    {"name": "笔记标题", "type": "text"},
    {"name": "笔记类型", "type": "select", "multiple": False,
     "options": [{"name": "图文"}, {"name": "视频"}]},
    {"name": "作者", "type": "text"},
    {"name": "标签", "type": "text"},
    {"name": "正文", "type": "text"},
    {"name": "图片链接", "type": "text"},
    {"name": "点赞数", "type": "number"},
    {"name": "收藏数", "type": "number"},
    {"name": "评论数", "type": "number"},
    {"name": "分享数", "type": "number"},
    {"name": "发布时间", "type": "datetime"},
    {"name": "笔记链接", "type": "text"},
    {"name": "note_id", "type": "text"},
    {"name": "抓取时间", "type": "datetime"},
]


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


# ---------------------------------------------------------------- 建表（每个账号各自一份）
def _dig(obj, paths, default=""):
    """按候选路径依次取值，兼容 lark-cli 不同版本/封装层的返回结构"""
    for path in paths:
        cur = obj
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    return default


def is_provisioned():
    """当前是否已经有可用的表格坐标"""
    st = load_settings()
    return bool(st.get("base_token") and st.get("table_id"))


def require_provisioned():
    """读写记录前的守卫：没建表就给出明确指引，而不是抛权限错误"""
    st = load_settings()
    if not (st.get("base_token") and st.get("table_id")):
        raise FeishuError("尚未创建飞书表格，请先在工作台点击「创建我的表格」")
    return st


def reset_settings():
    """清空表格坐标——换账号时使用"""
    return save_settings({"base_token": "", "table_id": "", "base_url": ""})


def list_tables(base_token):
    """列出某个 base 下的所有表"""
    res = run(["base", "+table-list", "--base-token", base_token, "--as", "user"], timeout=90)
    if isinstance(res, dict) and res.get("ok") is False:
        raise FeishuError(json.dumps(res.get("error"), ensure_ascii=False))
    data = (res.get("data") if isinstance(res, dict) else None) or {}
    return data.get("tables") or data.get("items") or []


def provision_base(name=BASE_NAME, table_name=TABLE_NAME):
    """
    在当前登录账号自己的飞书空间里新建一张多维表格，并写好字段结构。
    每个账号各建一份，彼此互不干扰、也不需要任何额外文档授权。
    返回写入本地配置后的 settings。
    """
    fields = json.dumps(FIELD_SCHEMA, ensure_ascii=False)
    res = run([
        "base", "+base-create",
        "--name", name,
        "--table-name", table_name,
        "--fields", fields,
        "--format", "json",
        "--as", "user",
    ], timeout=180)

    if isinstance(res, dict) and res.get("ok") is False:
        raise FeishuError(json.dumps(res.get("error"), ensure_ascii=False))

    base_token = _dig(res, [
        ["data", "base", "base_token"], ["data", "base_token"],
        ["data", "base", "app_token"], ["data", "app", "app_token"],
        ["data", "app_token"],
    ])
    base_url = _dig(res, [
        ["data", "base", "url"], ["data", "url"],
        ["data", "base", "base_url"], ["data", "app", "url"],
    ])
    table_id = _dig(res, [
        ["data", "table_id"], ["data", "default_table_id"],
        ["data", "base", "default_table_id"], ["data", "app", "default_table_id"],
        ["data", "table", "table_id"], ["data", "table", "id"],
    ])

    if not base_token:
        raise FeishuError("建表成功但未返回 base_token：" + json.dumps(res, ensure_ascii=False)[:180])

    # table_id 兜底：按表名回查
    if not table_id:
        try:
            tables = list_tables(base_token)
        except FeishuError:
            tables = []
        hit = next((t for t in tables if (t.get("name") or "") == table_name), None) or (tables[0] if tables else {})
        table_id = hit.get("table_id") or hit.get("id") or ""

    if not table_id:
        raise FeishuError("建表成功但未返回 table_id，请在设置里手动填写")

    if not base_url:
        base_url = "https://feishu.cn/base/" + base_token

    return save_settings({"base_token": base_token, "table_id": table_id, "base_url": base_url})


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
    st = require_provisioned()
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
    st = require_provisioned()
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
    st = require_provisioned()
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

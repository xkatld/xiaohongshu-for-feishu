# -*- coding: utf-8 -*-
"""
小红书统计工作流
=====================================================
流程：输入小红书分享链接 → 抓取笔记数据 → 写入飞书多维表格

用法：
    python xhs_workflow.py "<分享链接或分享文案>"
    python xhs_workflow.py --file links.txt      # 批量：每行一个链接
    python xhs_workflow.py                       # 使用内置示例链接
"""
import os
import sys
import json
import time
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xhs_core import fetch_note, get_cookie_from_env, XHSError  # noqa: E402

# ---------------------------------------------------------------- 配置
BASE_TOKEN = "S6IGbRWTeaualFsWEkBc81zBn0g"
TABLE_ID = "tbl1c8KxkRxC2hCk"
BASE_URL = "https://my.feishu.cn/base/S6IGbRWTeaualFsWEkBc81zBn0g"
LARK_CLI = os.environ.get("LARK_CLI", "lark-cli")

DEMO = ("54 【这棵树到底结了多少苹果？ - 小九探秘 | 小红书 - 你的生活兴趣社区】 😆 LwO7RdlpBW92tVD 😆 "
        "https://www.xiaohongshu.com/discovery/item/6a9d7ef9000000002b013bdb?source=webshare&xhsshare=pc_web"
        "&xsec_token=ABk_3AeD7lWQQxMP3aKKHI4wezJIBoN6XSfHvkOW4XI5E=&xsec_source=pc_share")

# 临时目录（lark-cli 对 Windows 短名反斜杠路径的 --output 支持不佳，统一用正斜杠完整路径）
TMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmp")


def tmp_path(prefix, suffix):
    os.makedirs(TMP_DIR, exist_ok=True)
    return os.path.join(TMP_DIR, f"{prefix}{int(time.time() * 1000)}{suffix}").replace("\\", "/")


# ---------------------------------------------------------------- 数据映射
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


# ---------------------------------------------------------------- 飞书写入
def _run_lark(args, timeout=60):
    cmd = [LARK_CLI] + args
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, shell=(os.name == "nt"),
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise RuntimeError(f"lark-cli 返回非 JSON：{out[:400]}")


def push_to_feishu(records):
    """批量写入飞书多维表格，返回 record_id 列表"""
    if not records:
        return []
    payload = {"create_records": records}
    path = tmp_path("xhs_", ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    try:
        res = _run_lark([
            "base", "+record-batch-create",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--json", "@" + path,
            "--as", "user",
        ])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if not res.get("ok"):
        raise RuntimeError(f"写入飞书失败：{json.dumps(res.get('error'), ensure_ascii=False)}")
    data = res.get("data") or {}
    return data.get("record_id_list") or data.get("records") or []


# ---------------------------------------------------------------- 主流程
def run_one(share_text, cookie):
    print(f"\n[1/3] 解析链接 ...")
    info = fetch_note(share_text, cookie)
    print(f"      标题: {info['title']}")
    print(f"      作者: {info['author']}  类型: {info['type']}")
    print(f"      标签: {info['tags_text'] or '（无）'}")
    print(f"      图片: {len(info['images'])} 张")
    print(f"      互动: 赞{info['liked']} 藏{info['collected']} 评{info['comment']} 转{info['share']}")

    print(f"[2/3] 组装记录 ...")
    record = build_record(info)

    print(f"[3/3] 写入飞书多维表格 ...")
    ids = push_to_feishu([record])
    print(f"      写入成功 record_id: {ids}")
    return info, ids


def main():
    args = sys.argv[1:]
    cookie = get_cookie_from_env()
    if not cookie:
        print("!! 未找到 cookie，请把小红书 cookie 写入 cookies/xhs_cookie.txt")
        sys.exit(1)

    targets = []
    if args and args[0] == "--file":
        with open(args[1], "r", encoding="utf-8") as f:
            targets = [ln.strip() for ln in f if ln.strip()]
    elif args:
        targets = [" ".join(args)]
    else:
        targets = [DEMO]

    ok, fail = 0, 0
    for t in targets:
        try:
            run_one(t, cookie)
            ok += 1
        except XHSError as e:
            print(f"  [失败] 抓取错误: {e}")
            fail += 1
        except Exception as e:
            print(f"  [失败] {e}")
            fail += 1
        time.sleep(1.5)

    print(f"\n完成：成功 {ok} 条，失败 {fail} 条")
    print(f"表格地址：{BASE_URL}")


if __name__ == "__main__":
    main()

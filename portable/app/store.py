# -*- coding: utf-8 -*-
"""
本地数据存储层
--------------------------------------------------
便携包的主存储：抓取结果先落本地 JSON，保证离线也能用；
飞书写入作为云端同步，成功后在记录上打 synced 标记。
"""
import os
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")


def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_notes():
    _ensure()
    if not os.path.exists(NOTES_FILE):
        return []
    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_notes(notes):
    _ensure()
    tmp = NOTES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    os.replace(tmp, NOTES_FILE)


def upsert_local(info, synced=False, record_id=""):
    """写入/更新一条本地记录，返回 (action, note)"""
    notes = load_notes()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for n in notes:
        if n.get("note_id") == info["note_id"]:
            n.update(info)
            n["synced"] = synced or n.get("synced", False)
            n["record_id"] = record_id or n.get("record_id", "")
            n["updated_at"] = now
            save_notes(notes)
            return "updated", n
    rec = dict(info)
    rec["synced"] = synced
    rec["record_id"] = record_id
    rec["created_at"] = now
    rec["updated_at"] = now
    notes.insert(0, rec)
    save_notes(notes)
    return "created", rec


def mark_synced(note_id, record_id):
    notes = load_notes()
    changed = False
    for n in notes:
        if n.get("note_id") == note_id:
            n["synced"] = True
            n["record_id"] = record_id
            changed = True
            break
    if changed:
        save_notes(notes)


def delete_note(note_id):
    notes = load_notes()
    left = [n for n in notes if n.get("note_id") != note_id]
    if len(left) != len(notes):
        save_notes(left)
        return True
    return False


def to_csv(notes):
    """导出 CSV 文本（带 BOM，Excel 直接打开不乱码）"""
    cols = [("note_id", "笔记ID"), ("title", "标题"), ("type", "类型"), ("author", "作者"),
            ("tags_text", "标签"), ("desc", "正文"), ("liked", "点赞"), ("collected", "收藏"),
            ("comment", "评论"), ("share", "分享"), ("publish_time", "发布时间"),
            ("ip_location", "IP归属"), ("url", "笔记链接"), ("fetch_time", "抓取时间")]
    lines = [",".join(name for _, name in cols)]
    for n in notes:
        row = []
        for key, _ in cols:
            v = str(n.get(key, "") or "").replace('"', '""').replace("\n", " ")
            row.append(f'"{v}"')
        lines.append(",".join(row))
    return "\ufeff" + "\n".join(lines)

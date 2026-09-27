# -*- coding: utf-8 -*-
"""
本地数据存储层
--------------------------------------------------
便携包的主存储：抓取结果先落本地 JSON，保证离线也能用；
飞书写入作为云端同步，成功后在记录上打 synced 标记。
"""
import os
import re
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(ROOT, "data")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")

# 本地图片：data/images/<note_id>/01.jpg、02.png …
IMAGES_DIR = os.path.join(DATA_DIR, "images")
_SAFE_ID = re.compile(r"^[0-9a-zA-Z_\-]{1,64}$")
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp", ".heic")


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


# ---------------------------------------------------------------- 本地图片
def images_root():
    return IMAGES_DIR


def note_image_dir(note_id, create=False):
    """
    返回某条笔记的图片目录 data/images/<note_id>/。

    note_id 先过白名单（只允许字母、数字、下划线、横线），非法值直接拒绝 ——
    这样即使前端传来 "../" 这类东西也走不出 data/images/ 这一层。
    """
    nid = str(note_id or "").strip()
    if not _SAFE_ID.match(nid):
        return ""
    p = os.path.join(IMAGES_DIR, nid)
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def list_note_images(note_id):
    """该笔记本地已保存的图片路径（按文件名排序）"""
    d = note_image_dir(note_id)
    if not d or not os.path.isdir(d):
        return []
    out = []
    try:
        for name in sorted(os.listdir(d)):
            fp = os.path.join(d, name)
            if os.path.isfile(fp) and os.path.splitext(name)[1].lower() in _IMG_EXT:
                out.append(fp)
    except OSError:
        return []
    return out


def clear_note_images(note_id):
    """
    重新抓取前清掉该笔记自己的旧图（笔记可能删了图，避免新旧混在一起）。

    只在 data/images/<note_id>/ 这一层删图片文件：不递归、不删子目录、
    不碰这个目录以外的任何东西。
    """
    d = note_image_dir(note_id)
    if not d or not os.path.isdir(d):
        return 0
    n = 0
    for name in os.listdir(d):
        fp = os.path.join(d, name)
        if os.path.isfile(fp) and os.path.splitext(name)[1].lower() in _IMG_EXT:
            try:
                os.remove(fp)
                n += 1
            except OSError:
                pass
    return n


def image_counts():
    """一次扫描 data/images/，返回 {note_id: {"count": 张数, "first": 首图文件名}}"""
    out = {}
    if not os.path.isdir(IMAGES_DIR):
        return out
    try:
        for entry in os.scandir(IMAGES_DIR):
            if not entry.is_dir():
                continue
            names = []
            try:
                for f in os.scandir(entry.path):
                    if f.is_file() and os.path.splitext(f.name)[1].lower() in _IMG_EXT:
                        names.append(f.name)
            except OSError:
                pass
            if names:
                names.sort()
                out[entry.name] = {"count": len(names), "first": names[0]}
    except OSError:
        pass
    return out


def with_image_counts(notes):
    """给记录列表补上 local_images（张数）与 local_first（首图文件名）"""
    counts = image_counts()
    for n in notes:
        hit = counts.get(str(n.get("note_id") or "")) or {}
        n["local_images"] = hit.get("count", 0)
        n["local_first"] = hit.get("first", "")
    return notes


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

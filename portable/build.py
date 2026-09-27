# -*- coding: utf-8 -*-
"""
便携包构建脚本
=====================================================
用法：
    python portable/build.py              # 完整构建（缺运行时则自动下载）
    python portable/build.py --check      # 只检查依赖是否齐备

流程：
    1. 确保 python/ 内置运行时存在（缺失则从 python.org 下载 embeddable 包）
    2. 确保 tools/lark-cli.exe 存在（缺失则尝试从本机 WorkBuddy 目录复制）
    3. 打包为 dist/xhs-workbench-portable-win.zip

注意：打包时会自动排除 config/xhs_cookie.txt、config/settings.json 与
data/notes.json、data/images/ —— 保证打包者自己的 Cookie、飞书表格地址、
本地数据与笔记图片都不会外泄；
使用者首次运行登录飞书后，程序会在 TA 自己的空间里新建一张表格。
"""
import os
import sys
import time
import zipfile
import shutil
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DIST = os.path.join(ROOT, "dist")

PY_DIR = os.path.join(HERE, "python")
TOOLS_DIR = os.path.join(HERE, "tools")
LARK_EXE = os.path.join(TOOLS_DIR, "lark-cli.exe")

PY_VER = "3.13.12"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
TOP_NAME = "xhs-workbench-portable"
OUT_ZIP = os.path.join(DIST, "xhs-workbench-portable-win.zip")

SKIP_DIRS = {"__pycache__", "_tmp", "images"}
SKIP_FILES = {
    os.path.join("config", "xhs_cookie.txt"),
    # 表格坐标必须由使用者登录后自行创建，绝不能把打包者自己的表格发出去
    os.path.join("config", "settings.json"),
    os.path.join("data", "notes.json"),
}
# lark-cli 在本机的常见位置（WorkBuddy 连接器自带）
LARK_CANDIDATES = [
    os.path.expandvars(r"%USERPROFILE%\.workbuddy\binaries\node\cli-connector-packages"
                       r"\node_modules\@larksuite\cli\bin\lark-cli.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\WorkBuddy\resources\app.asar.unpacked"
                       r"\node_modules\@larksuite\cli\bin\lark-cli.exe"),
]


def step(msg):
    print(f"\n>>> {msg}")


def ensure_python():
    if os.path.exists(os.path.join(PY_DIR, "python.exe")):
        print(f"  [跳过] Python 运行时已存在：{PY_DIR}")
        return True
    step(f"下载 Python {PY_VER} 嵌入式运行时")
    os.makedirs(PY_DIR, exist_ok=True)
    tmp_zip = os.path.join(PY_DIR, "_embed.zip")
    print(f"  来源：{PY_URL}")
    try:
        urllib.request.urlretrieve(PY_URL, tmp_zip)
    except Exception as e:
        print(f"  [失败] 下载出错：{e}")
        print("  可手动下载后解压到 portable/python/")
        return False
    with zipfile.ZipFile(tmp_zip) as z:
        z.extractall(PY_DIR)
    os.remove(tmp_zip)
    print("  完成")
    return True


def ensure_lark():
    if os.path.exists(LARK_EXE):
        print(f"  [跳过] lark-cli 已存在：{LARK_EXE}")
        return True
    step("准备 lark-cli.exe")
    os.makedirs(TOOLS_DIR, exist_ok=True)
    for cand in LARK_CANDIDATES:
        if os.path.exists(cand):
            shutil.copy2(cand, LARK_EXE)
            print(f"  已从本机复制：{cand}")
            return True
    print("  [失败] 未找到 lark-cli.exe")
    print("  请手动把 lark-cli.exe 放到 portable/tools/ 下")
    return False


def pack(out_path=None):
    step("打包 zip")
    os.makedirs(DIST, exist_ok=True)
    out = out_path or OUT_ZIP
    # 安全策略：绝不删除已有文件；同名时自动改用带时间戳的新文件名
    if os.path.exists(out):
        base, ext = os.path.splitext(out)
        out = f"{base}-{time.strftime('%Y%m%d-%H%M%S')}{ext}"
        print(f"  同名文件已存在，本次输出到：{os.path.basename(out)}")

    count, raw = 0, 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(HERE):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, HERE)
                if rel in SKIP_FILES:
                    continue
                z.write(fp, os.path.join(TOP_NAME, rel).replace("\\", "/"))
                count += 1
                raw += os.path.getsize(fp)

    size = os.path.getsize(out)
    print(f"  文件数：{count}")
    print(f"  原始：{raw / 1048576:.1f} MB  →  压缩：{size / 1048576:.1f} MB")
    print(f"  输出：{out}")
    return True


def main():
    print("=" * 56)
    print("  小红书笔记统计台 · 便携包构建")
    print(f"  目录：{HERE}")
    print("=" * 56)

    ok_py = ensure_python()
    ok_lark = ensure_lark()

    if "--check" in sys.argv:
        print(f"\n检查结果：Python={'OK' if ok_py else '缺失'}  "
              f"lark-cli={'OK' if ok_lark else '缺失'}")
        return 0 if (ok_py and ok_lark) else 1

    if not (ok_py and ok_lark):
        print("\n依赖不齐，已中止打包。")
        return 1

    pack()
    print("\n构建完成 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())

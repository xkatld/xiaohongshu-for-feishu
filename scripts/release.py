# -*- coding: utf-8 -*-
"""
发布 GitHub Release 并上传便携包
=====================================================
用法：
    python scripts/release.py v1.0.0
    python scripts/release.py v1.1.0 --notes "本次更新说明"
    python scripts/release.py v1.0.0 --file dist/自定义包名.zip

前置：
    · 已 `git push` 到 origin/main（Release 会打到 main 最新提交上）
    · 本机 git 已保存 github.com 凭据（Git Credential Manager）
    · 目标 zip 已由 portable/build.py 生成

说明：
    Release 会创建同名 tag；若 tag 已存在，接口会直接报错，不会重复创建。
"""
import os
import sys
import json
import argparse
import subprocess
import urllib.request
import urllib.error

REPO = "xkatld/xiaohongshu-for-feishu"
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ZIP = os.path.join(ROOT, "dist", "xhs-workbench-portable-win.zip")


def get_token():
    """从 git 凭据管理器读取 github.com 的 token"""
    out = subprocess.run(
        'printf "protocol=https\\nhost=github.com\\n\\n" | git credential fill',
        shell=True, capture_output=True, text=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("未能从 git 凭据中读取 GitHub token")


def api(url, token, method="GET", payload=None, raw=None, ctype="application/json", timeout=300):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "xhs-workbench-release",
    }
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = ctype
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def build_body(version, notes):
    extra = f"\n### 本次更新\n\n{notes}\n" if notes else ""
    return f"""## 小红书笔记统计台 {version}

粘贴小红书分享链接，自动抓取标题 / 正文 / 标签 / 图片 / 互动数据，写入飞书多维表格。

### 下载

**Windows 免安装版** —— 解压即用，无需安装 Python。
{extra}
### 使用方法

1. 解压到任意目录（路径不要带特殊符号）
2. 双击 `启动工作台.bat`
3. 浏览器自动打开工作台，粘贴链接即可抓取

首次使用需配置：

| 配置项 | 获取方式 |
|---|---|
| 小红书 Cookie | 登录 xiaohongshu.com → F12 → Network → 复制请求头里的 Cookie，粘贴到「设置」 |
| 飞书账号 | 页面「设置 → 飞书账号 → 登录飞书」，在浏览器完成扫码授权 |

### 特性

- 支持整段分享文案 / 完整链接 / `xhslink` 短链 / `note_id` 四种输入
- 抓取标题、正文、标签、图片、作者、点赞、收藏、评论、分享、发布时间、IP 归属
- 双轨存储：数据先落本地 `data/notes.json`，飞书作为云同步，断网也能用
- 幂等写入：同一笔记重复抓取自动**更新**而非新增，可刷新互动数据
- 一键导出 CSV / JSON 备份；PC / 移动端自适应

### 环境要求

- Windows 10 / 11（64 位）
- 内置 Python 3.13.12 运行时与 lark-cli，无需安装依赖
"""


def main():
    ap = argparse.ArgumentParser(description="发布 GitHub Release")
    ap.add_argument("tag", help="版本号，例如 v1.0.0")
    ap.add_argument("--file", default=DEFAULT_ZIP, help="要上传的 zip 路径")
    ap.add_argument("--name", default="", help="上传后的文件名（默认沿用 --file 的文件名）")
    ap.add_argument("--notes", default="", help="本次更新说明")
    ap.add_argument("--target", default="main", help="目标分支，默认 main")
    args = ap.parse_args()

    tag = args.tag if args.tag.startswith("v") else "v" + args.tag
    zip_path = os.path.abspath(args.file)
    if not os.path.exists(zip_path):
        raise SystemExit(f"未找到待上传文件：{zip_path}\n请先运行 python portable/build.py")

    token = get_token()
    print(f"凭据就绪（长度 {len(token)}）")
    print(f"版本：{tag}")
    print(f"文件：{zip_path}（{os.path.getsize(zip_path) / 1048576:.1f} MB）")

    print("\n[1/2] 创建 Release ...")
    rel = api(f"{API}/repos/{REPO}/releases", token, "POST", {
        "tag_name": tag,
        "target_commitish": args.target,
        "name": f"{tag} · 小红书笔记统计台（Windows 便携版）",
        "body": build_body(tag, args.notes),
        "draft": False,
        "prerelease": False,
    })
    print(f"  {rel.get('html_url')}")

    print("\n[2/2] 上传附件 ...")
    asset_name = args.name or os.path.basename(zip_path)
    upload = rel["upload_url"].split("{")[0] + f"?name={asset_name}"
    with open(zip_path, "rb") as f:
        blob = f.read()
    asset = api(upload, token, "POST", raw=blob, ctype="application/zip")
    print(f"  {asset.get('browser_download_url')}")

    print(f"\n发布页：{rel.get('html_url')}")
    print(f"下载直链：{asset.get('browser_download_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

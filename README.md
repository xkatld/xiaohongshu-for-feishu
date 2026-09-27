# 小红书笔记统计工作流

输入小红书分享链接 → 自动抓取笔记数据 → 保存到飞书多维表格。

## 一、飞书表格

> 下表是**开发机自己用的**表格，只用于本地调试。
> 便携版**不内置任何表格地址**：使用者登录飞书后，程序会在 TA 自己的空间里自动新建一张（见第九节）。

| 项目 | 值 |
|---|---|
| 表格名称 | 小红书笔记统计 |
| 地址 / base_token / table_id | 不在文档中记录 —— 属本机私有配置，见本机 `portable/config/settings.json`（该文件已排除出 git 与打包） |

**字段**：笔记标题、笔记类型（图文/视频）、作者、标签、正文、图片链接、点赞数、收藏数、评论数、分享数、发布时间、笔记链接、note_id、抓取时间。

## 二、项目结构

```
├── workbench.html            工作台页面（单文件、全内联、无外部依赖）
├── cookies/
│   └── xhs_cookie.txt        小红书登录 Cookie（失效时替换此文件）
├── scripts/
│   ├── xhs_core.py           抓取核心：链接解析 + 页面数据抽取
│   ├── xhs_workflow.py       工作流主脚本：抓取 → 写飞书
│   └── xhs_server.py         本地服务：提供工作台页面与接口
└── README.md
```

## 三、三种用法

### 1. 可视化工作台（推荐）

```bash
python scripts/xhs_server.py
```

浏览器打开 <http://127.0.0.1:8787>，粘贴链接 → 点击「抓取并保存到飞书」。
页面同时展示数据概览、类型分布、点赞 Top5 与已收录笔记列表。

### 2. 命令行单条抓取

```bash
python scripts/xhs_workflow.py "粘贴分享链接或整段分享文案"
```

### 3. 命令行批量抓取

把链接逐行写入 `links.txt`，然后：

```bash
python scripts/xhs_workflow.py --file links.txt
```

## 四、支持的输入形式

以下四种都能自动识别：

- 完整分享文案（含表情、标题、口令）
- `https://www.xiaohongshu.com/discovery/item/{id}?xsec_token=...`
- `https://www.xiaohongshu.com/explore/{id}`
- `https://xhslink.com/xxxx` 短链（自动跟随跳转）

## 五、Cookie 维护

Cookie 存放在 `cookies/xhs_cookie.txt`，从浏览器开发者工具中复制完整 Cookie 覆盖即可。

出现以下情况说明 Cookie 已失效，需重新获取：

- 抓取报错「页面中未找到 \_\_INITIAL_STATE\_\_」
- 报错「页面数据中没有笔记内容」

**关键字段**：`a1`、`web_session`、`webId` 至少要存在。

## 六、去重规则

同一 `note_id` 再次抓取时不会新增记录，而是**更新原有记录**（用于刷新点赞/收藏等互动数据）。接口返回中的 `action` 字段可区分：`created`（新增）/ `updated`（更新）。

## 七、常见问题

| 现象 | 处理 |
|---|---|
| 抓取报错 cookie 相关 | 更新 `cookies/xhs_cookie.txt` |
| 图片不显示 | 图片经本地服务代理转发；确认服务在运行 |
| 端口被占用 | 设置环境变量 `XHS_PORT=8888` 后重启 |
| 表格打开无权限 | 表格归属当前飞书账号「咱们裸熊」 |

## 八、技术说明

- 抓取原理：携带 Cookie 请求笔记详情页 HTML，解析页面内 `window.__INITIAL_STATE__` 中的 `note.noteDetailMap` 数据。
- 页面数据含 `new Map(...)` 等非标准 JSON 表达式，脚本内置了构造器剥离与括号配对解析。
- 写入飞书通过 `lark-cli` 完成，无需额外配置。
- 工作台页面零外部依赖，图片经 `/api/img` 代理以绕过小红书防盗链。

## 九、便携版（Windows 免安装）

给不方便装 Python / 需要拷贝到其他电脑的场景使用。源码与构建脚本位于 `portable/`，产物为单个 zip。

### 产物

```
dist/xhs-workbench-portable-win.zip        约 24 MB
```

解压后目录：

```
xhs-workbench-portable/
├── 启动工作台.bat          双击运行
├── 使用说明.txt            给最终用户看的说明
├── python/                 Python 3.13 嵌入式运行时（21 MB，免安装）
├── app/                    程序代码（零第三方依赖，仅标准库）
│   └── web/index.html      工作台页面
├── tools/lark-cli.exe      飞书操作工具（48 MB，自带运行时）
├── config/                 配置目录（Cookie、表格坐标；首次运行自动生成）
└── data/                   本地数据（notes.json，首次运行自动创建）
```

### 首次使用：三步（工作台内置引导）

这是**开源工具，不是共享服务**。每个使用者用**自己的飞书应用 + 自己的账号**，各建各的表：

| 步骤 | 做什么 | 实现 |
|---|---|---|
| 1 | 绑定使用者自己的飞书应用 | `lark-cli config init --new`（飞书官方向导，浏览器里创建），或手动填 App ID/Secret（**先校验再写入，失败回滚**）|
| 2 | 登录自己的账号 | `auth login`（Device Flow）|
| 3 | 创建自己的表格 | `base +base-create`，14 个字段一次建好 |

三步状态由 `/api/status` 的 `steps` 字段统一暴露，前端渲染成引导卡，全部完成后自动隐藏。

凭据全部落在使用者自己的用户目录 `~/.lark-cli/`，**不在分发包内、也不属于本仓库**。

> 若第 1 步用手动填写：程序会先调用 `tenant_access_token/internal` 校验凭据，
> 只有校验通过才写本机配置，并对 `config.json` 做快照回滚 —— 填错不会污染已有配置。

### 设计要点

| 项目 | 说明 |
|---|---|
| 零第三方依赖 | 用标准库 `urllib` 替代 `requests`，无需 pip 安装 |
| 双轨存储 | 抓取结果先落本地 `data/notes.json`，飞书作为云端同步；断网也能用 |
| 免配置迁移 | `lark-cli.exe` 为自包含单文件，无需 Node 环境 |
| Cookie 不入包 | 打包时排除 `config/xhs_cookie.txt`，新电脑在页面「设置」里填一次即可 |
| 表格不入包 | 打包时排除 `config/settings.json`，使用者登录后自行建表，绝不外泄开发者的表格 |
| 应用各自申请 | 不内置任何人的 App ID/Secret，使用者走飞书官方向导获得自己的应用 |
| 端口自适应 | 8787 被占用时自动顺延到 8788、8789… |
| bat 编码 | 「启动工作台.bat」为 **GBK + CRLF**（中文 Windows 默认代码页 936），`.gitattributes` 已禁止 git 对其做任何转换 |

> **改 bat 的注意事项**：千万不要用默认 UTF-8 + LF 保存。cmd 不认 LF 分行，且会把 UTF-8 中文按 GBK 解析成乱码并拆成独立"命令"，表现为满屏「不是内部或外部命令」且服务起不来。用编辑器另存为 ANSI/GBK 编码、Windows(CRLF) 行尾。

### 源码结构（`portable/`）

```
portable/
├── build.py              一键构建脚本
├── app/                  程序代码（零第三方依赖，仅标准库）
│   ├── xhs_core.py       抓取核心（urllib 实现）
│   ├── feishu.py         飞书操作（调用内置 lark-cli）
│   ├── store.py          本地存储
│   ├── xhs_server.py     本地服务
│   └── web/index.html    工作台页面
├── config/               配置目录（Cookie、表格坐标；打包时整体排除）
├── 启动工作台.bat
├── 使用说明.txt
├── python/               内置运行时（构建时自动下载，不入库）
└── tools/lark-cli.exe    飞书工具（构建时自动获取，不入库）
```

### 重新打包

```bash
python portable/build.py            # 完整构建（缺运行时会自动下载）
python portable/build.py --check    # 只检查依赖是否齐备
```

> 注意：`portable/python/`、`portable/tools/`、`dist/` 已加入 `.gitignore`。分发建议走 GitHub Release，不要提交进仓库。构建脚本不会删除已有文件，同名时自动改用带时间戳的新文件名。


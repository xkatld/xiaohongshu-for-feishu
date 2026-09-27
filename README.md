# 小红书笔记统计工作流

输入小红书分享链接 → 自动抓取笔记数据 → 保存到飞书多维表格。

## 一、飞书表格

| 项目 | 值 |
|---|---|
| 表格名称 | 小红书笔记统计 |
| 地址 | https://my.feishu.cn/base/S6IGbRWTeaualFsWEkBc81zBn0g |
| base_token | `S6IGbRWTeaualFsWEkBc81zBn0g` |
| table_id | `tbl1c8KxkRxC2hCk` |

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

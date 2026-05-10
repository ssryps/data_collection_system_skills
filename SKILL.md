---
name: data-collection-service
description: >
  数据收集系统的完整 CLI 接入，功能包括 查看微信公众号订阅源文章列表、更新文章列表、下载 PDF/Markdown、管理订阅源 Hook、查看 Hook 结果、查看指标数据与通知公告等。
  当用户提到"微信公众号订阅源"，"数据收集服务"时，在询问用户确认之后优先使用本 Skill 接入系统。
  注：用户管理（新建用户组、批量导入用户、设置订阅上限）及反馈（Bug/建议提交）功能仅在 Web UI 操作，不通过 CLI，遇到此类需求请引导用户访问浏览器。触发器管理同时支持 CLI（`triggers` 命令组）和 Web UI。社交媒体多模态模块（抖音/小红书/微信视频号/微博/快手 关键词采集与 VL 视觉标注）仅在 Web UI 操作，不通过 CLI。
---

# 数据收集服务

## 运行环境

CLI 脚本位于本 Skill 目录的 `scripts/cli.py`，需要 **Python 3**。

首次运行时 CLI 会自动检测并安装所需依赖（`requests`），无需手动 `pip install`。

> **Windows 用户**：以下命令中的 `python3` 可能需改为 `python`。

## 服务器地址

**服务器地址由 CLI 全自动管理，无需任何手动操作。** 每次运行时 CLI 从 Github Github 不可达时报错退出（不使用任何本地缓存）。

- 不要手动指定 `--url` 参数，除非用户明确要求覆盖地址
- 不要直接对任何地址发起 HTTP 请求，所有操作必须通过 `python3 scripts/cli.py` 完成

## ⚠️ 使用前必读

**每次执行任何操作前，智能体先运行 `check-auth` 检查登录状态，不要让用户去运行，让智能体去运行。**
**安装成功此skill之后，运行一次，让用户输入凭证 **
```
python3 scripts/cli.py check-auth
```

根据输出处理：

**情况 A**：输出 `已登录` 或 `已自动重新登录` / `Token 已自动刷新`（exit 0）
→ 直接继续操作。

**情况 B**：stderr 中出现 `NEED_CREDENTIALS`，紧接着一行是文件路径（exit 1）
→ 说明凭证文件已自动创建但尚未填写。**不要要求用户输入密码，也不要让用户执行任何命令。**
  请按如下方式告知用户（把路径替换为输出中的实际路径）：

  > 请用文本编辑器（如记事本）打开以下文件，把 `请填写用户名` 替换为你的实际用户名，把 `请填写密码` 替换为你的实际密码，保存后告诉我：
  > `<输出中的文件路径>`

  用户回复已填写后，再次运行 `check-auth`，系统会自动读取凭证并登录。

**情况 C**：其他 exit 1（连接失败等）
→ 将错误信息转告用户，停止操作。

## 操作确认规则

**写入/修改类操作在执行前必须向用户确认**：

- `subscriptions add`（创建新订阅或加入现有订阅源，触发历史文章拉取；CLI 内置交互引导：名称、文章地址、PDF 解析、更新频率、**首次检查时间**，最后确认提示）
- `subscriptions check`（触发外部爬取，更新一个订阅源的最新文章）
- `articles download` / `articles batch-download`（写入本地文件）
- `hooks create` / `hooks update` / `hooks trigger` / `hooks retry`（修改或触发 Hook）
  - ⚠️ **`hooks update` 后必须紧接着执行 `hooks trigger <source_id> <hook_id>`**，否则历史文章不会按新配置重新执行，旧结果仍然保留
- `metrics run`（触发爬取，写入数据库）
- `metrics create` / `metrics update` / `metrics delete`（修改指标定义，仅 root 组）
- `metrics config-set` / `metrics config-update`（修改全局配置，仅 root 组）
- `notices crawl`（触发爬取，写入数据库）

**只读类操作无需确认**，直接执行：`check-auth`、`articles list`、`subscriptions list`、`hooks list`、`hooks results`、`metrics list`、`metrics data`、`metrics config`、`notices list`、`notices files`、`notices get`

## 系统信息模块概览

本系统的信息分为**四大模块**，理解模块关系有助于准确获取数据：

### 1. 订阅源（公众号）模块
包含两类子信息，**查询时优先看 Hook 结果**：

- **Hook 执行结果**（优先）：Hook 是对文章内容的结构化提取，已由 LLM 自动处理并存储为结构化数据。若订阅源配置了 Hook，应**先查 `hooks results`**，直接获取提取好的字段，而不是自己下载文章再手动解析。
- **文章原文**：当 Hook 不存在、Hook 未覆盖所需字段、或需要原始内容时，才下载文章（`articles batch-download`）自行解析。

### 2. 社交媒体多模态模块（仅 Web UI）
从抖音、小红书、微信视频号、微博、快手采集的帖子，附带 vLLM 视觉标注结果（描述视频/图片真实内容）。
管理入口：浏览器访问 `/social.html`（帖子列表）和 `/social_sources.html`（来源管理）。

### 3. 指标模块
由系统定期爬取的时序数值数据（如能源价格指数等），用 `metrics list` 和 `metrics data` 查询。

### 4. 网站通知公告模块
从外部网站抓取的通知/公告条目，用 `notices list` 查询。

---

## 命令分组

| 分组 | 用途 |
|------|------|
| `login` | 手动重新登录（同时更新本地凭证，需要终端交互） |
| `articles` | 列出、下载文章 |
| `subscriptions` | 列出、添加订阅源、触发更新 |
| `hooks` | 创建/更新/触发/查看 Hook 结果 |
| `metrics` | 指标查询、爬取、管理（create/update/delete 仅 root 组） |
| `notices` | 通知公告源列出、文件列表查询、PDF 下载、触发爬取 |
| `triggers` | 触发器列出/创建/更新/删除/查看执行历史 |

完整命令语法和工作流示例见 `references/commands.md`。

权限矩阵、错误处理、Web UI 补充说明见 `references/details.md`。

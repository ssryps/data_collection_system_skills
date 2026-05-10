# data-collection-service

数据收集系统 Skill / CLI，提供微信公众号文章订阅与爬取、Hook 自动化信息提取、电力指标监控、通知公告爬取等功能的完整接入。可在 Claude Code、LobeChat 等支持 Skill/插件的 AI 工具中使用，也可直接在终端调用。

## 前置依赖

仅需 **Python 3**，缺少 `requests` 时 CLI 首次运行会自动安装，无需手动操作。

## 安装方法

将本仓库克隆到 AI 工具的 skill 目录，**目录名必须为 `data-collection-service`**。

优先使用 GitHub（更稳定），Gitee 作为备用镜像：

```bash
# GitHub（推荐）
git clone https://github.com/ssryps/data_collection_system_skills.git /path/to/skills/data-collection-service

# Gitee（备用）
git clone https://gitee.com/ssryps/data_collection_system_skills.git /path/to/skills/data-collection-service
```

不同工具的 skill 目录位置：

| 工具 | Skill 目录 |
|------|-----------|
| Claude Code（Linux/macOS/WSL2） | `~/.claude/skills/` |
| Claude Code（Windows） | `%USERPROFILE%\.claude\skills\` |
| LobeChat（龙虾，Windows） | `%USERPROFILE%\.qclaw\workspace\skills\` |
| 其他工具 | 参考该工具文档中 Skill 目录的位置 |

## 使用方法

安装完成后，直接告诉 AI 助手你想查询什么数据即可，**无需执行任何命令**。

AI 助手会自动检查登录状态。首次使用时，它会在你的主目录下创建一个凭证文件，并告诉你用**文本编辑器（如记事本）**打开该文件，把 `请填写用户名` 和 `请填写密码` 替换成实际账号，保存后通知 AI 即可继续。凭证只保存在本地，不会传递给任何 AI 助手。

## 服务器地址

服务器地址存储在本仓库根目录的 `ip_port.txt`（JSON 格式）：

```json
{"ip": "1.2.3.4", "port": 8000}
```

CLI 启动时自动读取，服务器地址变更后手动更新该文件并重新 `git pull` 即可。

## 功能概览

- 文章：列出、下载（PDF / Markdown）、批量打包 ZIP
- 订阅源：列出、手动触发更新
- Hook：创建/更新/触发/查看执行结果（支持导出 CSV）
- 指标监控：查询历史数据、手动触发爬取、管理指标与全局配置（admin）
- 通知公告：列出来源、手动触发爬取

# 命令参考

## 完整命令速查

| 命令 | 说明 |
|------|------|
| `login` | 登录，保存 token 至 `~/.wechat_crawler_token` |
| `articles list` | 列出文章（`--source` 过滤，`--limit` 每页条数，`--search` 关键词，`--date-from/--date-to` 日期范围） |
| `articles download <id>` | 将指定文章加入下载队列 |
| `articles batch-download <ids>` | 批量下载为 ZIP（`-t pdf` 或 `-t md`，默认 md） |
| `subscriptions list` | 列出所有可见订阅源 |
| `subscriptions add` | 添加新订阅源（交互式引导，需要公众号名称、任意一篇文章地址、PDF解析开关、更新频率、首次检查时间） |
| `subscriptions check <id>` | 手动触发订阅源检查更新 |
| `hooks list <source_id>` | 列出某订阅源的所有 Hook |
| `hooks create <source_id>` | 创建新 Hook（`--hook-type full`/`judge_only`，默认 `full`） |
| `hooks update <source_id> <hook_id>` | 更新 Hook 配置（名称/描述/Prompt/启用状态） |
| `hooks trigger <source_id> <hook_id>` | 对该源所有已解析文章重新触发 Hook |
| `hooks retry <article_id> <hook_id>` | 对单篇文章重新触发 Hook |
| `hooks results <source_id> <hook_id>` | 查看 Hook 执行结果（`-o file.csv` 导出） |
| `metrics list` | 列出所有指标及最新值 |
| `metrics run <id>` | 手动触发指标爬取 |
| `metrics data <id>` | 获取指标全部历史数据（可导出 CSV） |
| `metrics create` | 新建指标（**仅 root 组**，含必填参数） |
| `metrics update <id>` | 更新指标（**仅 root 组**，只更新提供的字段） |
| `metrics delete <id>` | 删除指标（**仅 root 组**） |
| `metrics config` | 查看全局爬虫配置（**仅 root 组**） |
| `metrics config-set <json>` | 整体替换全局爬虫配置（**仅 root 组**） |
| `metrics config-update key=val ...` | 合并更新配置中的键（**仅 root 组**） |
| `notices list` | 列出通知公告源（含文件数、最后爬取时间） |
| `notices files <source_id>` | 列出某通知源下的公告文件（`--search` 关键词，`--limit` 条数） |
| `notices get <source_id> <file_id>` | 下载某条公告 PDF 到本地（`-o` 指定路径，默认以标题命名） |
| `notices crawl <id>` | 手动触发指定通知公告源爬取（后台异步执行） |
| `triggers list` | 列出可访问的触发器（admin 看全部，其他用户看本组） |
| `triggers get <id>` | 查看触发器详情（含执行代码） |
| `triggers create` | 创建触发器（`--name/--event-type/--code` 必填，`--code @file.py` 从文件读取） |
| `triggers update <id>` | 更新触发器（只更新提供的字段，`--enable/--disable` 切换状态） |
| `triggers delete <id>` | 删除触发器及所有执行记录（`-y` 跳过确认） |
| `triggers executions <id>` | 列出触发器的执行历史（`--limit` 条数，默认 20） |
| `triggers execution <exec_id>` | 查看单次执行详情（含 stdout/result/error） |

---

## 常见工作流

### 标准操作流程

```bash
# 每次操作前先检查登录状态（Token 过期时自动用保存的凭证续期）
python3 scripts/cli.py check-auth
# 若输出 NEED_CREDENTIALS + 文件路径：告知用户打开该文件填写账号密码，填完后再次 check-auth

# 已登录后正常操作
python3 scripts/cli.py subscriptions list
```

### 添加订阅源

```bash
# 交互式引导（不提供参数时逐项提示）
python scripts/cli.py subscriptions add

# 也可直接通过参数指定（省略交互提示）
python scripts/cli.py subscriptions add \
  --name "广东电力交易中心" \
  --url "https://mp.weixin.qq.com/s/xxxxxxx" \
  --pdf \
  --frequency 1d \
  --check-time "2026-04-28T08:00"
```

**参数说明：**
- `--name`：公众号名称，**必须与文章作者名完全一致**（后端会用 TikHub API 验证）
- `--url`：该公众号发布的任意一篇文章的微信链接（用于识别公众号唯一 ID）
- `--pdf` / `--no-pdf`：是否开启 PDF 解析（转为 Markdown，便于 AI 读取）；不指定则交互提示
- `--frequency`：更新频率，支持值：`none`（不自动）/ `12h` / `1d` / `2d` / `7d`；不指定则交互选择
- `--check-time`：首次检查时间，格式 `YYYY-MM-DDTHH:MM`（如 `2026-04-28T08:00`）；仅在 `--frequency` 非 `none` 时生效；不指定时交互引导，若直接回车则默认当前时间+5分钟

**返回行为：**
- `created`：该公众号首次添加，后台同时拉取历史文章（异步）
- `subscribed`：该公众号已被其他用户组订阅，本组加入订阅即可；文章共享，无需重复拉取
- 400 错误：公众号名称与文章作者不匹配 / 已订阅 / 是公开源无需订阅 / 达到私有源上限

---

### 触发订阅源更新并等待全流程完成

触发 `subscriptions check` 后，**一篇文章真正处理完毕**需经过以下阶段，缺一不可：

```
[触发更新] → [等待文章下载 & 解析] → [等待 Hook 执行完成（如有）] → ✅ 完成
```

**阶段一：文章下载与解析完成**

轮询 `articles list --source <source_id>`，确认所有新文章同时满足：
- `下载状态 = completed`
- `解析状态 = completed`

只要有一项不是 `completed`（如 `pending`、`processing`、`failed`），说明文章尚未就绪，需继续等待。每隔 15～30 秒轮询一次。

**阶段二：Hook 执行完成（若该订阅源配置了 Hook）**

先用 `hooks list <source_id>` 确认是否存在 Hook。若有，则对每个 Hook 轮询 `hooks results <source_id> <hook_id>`，确认新文章对应条目的 `状态` 字段为以下任一终态：

| 状态值 | 含义 |
|--------|------|
| `completed` | 判断命中，动作已执行完毕，`执行时间` 字段有值，可读取结果内容 |
| `judged` | 判断为不相关（`触发结果 = no`），Hook 不执行动作，但文章已处理完 |

终态因 Hook 类型不同而有差异：

| Hook 类型 | 判断结果 | 终态 | 有结果文件 |
|-----------|---------|------|-----------|
| `full`（完整） | yes | `completed` | ✓ |
| `full`（完整） | no | `judged` | ✗ |
| `judge_only`（仅判断） | yes | `completed` | ✗ |
| `judge_only`（仅判断） | no | `judged` | ✗ |

若条目尚未出现，或状态为 `pending` / `processing`，则需继续等待。

```bash
# 第一步：触发更新
python scripts/cli.py subscriptions check <source_id>

# 第二步：轮询文章状态（每 15~30 秒一次）
python scripts/cli.py articles list --source <source_id> --limit 20

# 第三步：确认是否有 Hook
python scripts/cli.py hooks list <source_id>

# 第四步：轮询 Hook 结果，直到新文章状态为 completed 或 judged
python scripts/cli.py hooks results <source_id> <hook_id>

# 完成后优先读 Hook 结果获取结构化数据（completed 的条目才有内容）
python scripts/cli.py hooks results <source_id> <hook_id> -o results.csv
```

---

### 查看文章与下载

```bash
# 查看某订阅源的文章（默认每页50条）
python scripts/cli.py articles list --source <source_id> --limit 20

# 按标题关键词搜索
python scripts/cli.py articles list --search "现货价格"

# 按日期范围过滤
python scripts/cli.py articles list --source <source_id> --date-from 2026-01-01 --date-to 2026-04-30

# 批量下载 Markdown（含图片）
python scripts/cli.py articles batch-download 1,2,3 -t md -o output.zip

# 批量下载 PDF
python scripts/cli.py articles batch-download 1,2,3 -t pdf -o output.zip
```

### Hook 管理

> ⚠️ **重要：更新 Hook 后必须手动触发全量重跑**
>
> `hooks update` 仅修改 Hook 的配置（Prompt、名称等），**不会自动对历史文章重新执行**。
> 更新完成后，必须紧接着执行 `hooks trigger <source_id> <hook_id>`，才能让所有已解析文章按新配置重新运行。
> 遗漏此步骤会导致旧结果仍保留，新配置只对更新后新收录的文章生效。

Hook 有两种类型，创建时通过 `--hook-type` 指定：

| 类型 | 说明 | 结果文件 |
|------|------|---------|
| `full`（默认） | 判断 + 操作两段 Prompt，判断为"是"后执行操作并保存结果 txt | 有 |
| `judge_only` | 仅判断 Prompt，判断后直接终态，不执行操作 | 无 |

```bash
# 列出订阅源的 Hook（含类型标签：[完整]/[仅判断]）
python scripts/cli.py hooks list <source_id>

# 创建完整 Hook（full，默认类型）
python scripts/cli.py hooks create <source_id> \
  --name "日报电价提取" \
  --judgment-prompt "这篇文章是否为电力现货市场日报？" \
  --action-prompt "提取日前市场均价、实时市场均价，以JSON输出"

# 创建仅判断 Hook（judge_only，无操作阶段，无需 --action-prompt）
python scripts/cli.py hooks create <source_id> \
  --hook-type judge_only \
  --name "现货日报标记" \
  --judgment-prompt "这篇文章是否为电力现货市场日报？"

# 创建 Hook（prompt 从文件读取，用 @路径 语法）
python scripts/cli.py hooks create <source_id> \
  --name "日报电价提取" \
  --judgment-prompt "@/path/to/judge.txt" \
  --action-prompt "@/path/to/action.txt"

# 更新 Hook（只更新提供的字段）
python scripts/cli.py hooks update <source_id> <hook_id> --name "新名称" --enable
python scripts/cli.py hooks update <source_id> <hook_id> --judgment-prompt "新的判断prompt"
python scripts/cli.py hooks update <source_id> <hook_id> --action-prompt "@/path/to/new_action.txt"
python scripts/cli.py hooks update <source_id> <hook_id> --name "新名称" --judgment-prompt "..." --disable

# ⚠️ 更新 Hook 后必须执行此步骤，对所有已解析文章重新运行（清除旧结果）
python scripts/cli.py hooks trigger <source_id> <hook_id>

# 对单篇文章重新运行某 Hook
python scripts/cli.py hooks retry <article_id> <hook_id>

# 查看结果 / 导出 CSV
python scripts/cli.py hooks results <source_id> <hook_id>
python scripts/cli.py hooks results <source_id> <hook_id> -o results.csv
```

### 指标查询与触发

```bash
# 查看所有指标及最新值（含最新日期、最后检查时间）
python scripts/cli.py metrics list

# 手动触发某指标立即爬取（写入数据库）
python scripts/cli.py metrics run <id>

# 获取某指标的全部历史数据（时序数据，适合分析）
python scripts/cli.py metrics data <id>
python scripts/cli.py metrics data <id> -o electricity_price.csv  # 导出 CSV
```

### 指标管理（仅 root 组）

**必填参数说明：**
- `--pk-col`：主键列名，CSV 结果中唯一标识行的列（通常是日期，如 `date`）
- `--val-col`：主要值列名，展示的核心数值列（如 `value`）
- `--sort-col`：排序列名，升序排序后取最后行为最新值（通常与主键列相同）
- `--code`：爬虫代码，支持直接字符串或 `@文件路径`（如 `@crawler.py`）
- `--metric-group-id`：可选，指定所属指标组 ID（不填则放入默认组「默认指标组」；指标组在 Web UI「管理指标组」中管理）

**指标组说明：**

指标按「指标组」分组管理，每个指标组统一控制对哪些用户组可见（public 或指定用户组）。
系统自带一个不可删除的「默认指标组」作为兜底，其他指标组均为用户自行创建的普通组。
通过 CLI 创建指标时可用 `--metric-group-id` 指定组；创建新指标组请在 Web UI「指标监控 → 管理指标组」中操作。

**爬虫代码约定**：
- 将 `pandas.DataFrame` 赋给 `result` 变量（沙盒已预装 pandas）
- 返回空 DataFrame（0 行）会被框架视为失败并记录错误，不 upsert 历史数据
- 每个指标的列结构（`columns_schema`）在首次爬取后自动保存；后续如列集合发生变化，框架报错并中止 upsert
- 通过 `args.get('key')` 读取全局配置中的 token、密钥等参数

**示例：进口现货 LNG 到岸价格**（来源：上海石油天然气交易中心）

```python
import requests, pandas as pd
from datetime import datetime

url = "https://www.shpgx.com/marketzhishu/dataList2"
headers = {
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': 'https://www.shpgx.com',
    'Referer': 'https://www.shpgx.com/html/jkxhLNGdajglssj.html',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'X-Requested-With': 'XMLHttpRequest',
}
post_data = {
    'zhishukind': '9', 'type': 'zs', 'starttime': '', 'endtime': '',
    'start': 0, 'length': 100, 'ts': str(int(datetime.now().timestamp() * 1000))
}
resp = requests.post(url, headers=headers, data=post_data, timeout=30)
resp.raise_for_status()
r = resp.json()
data_list = r.get('root', []) or r.get('data', []) or []

rows = []
for item in data_list:
    date = item.get('strdate', '') or item.get('date', '')
    tradeprice = str(item.get('tradeprice', ''))
    # tradeprice 格式："May:16.837,Jun:16.484,Jul:16.508,"
    # m1 = M+1 近月，m2 = M+2，m3 = M+3
    prices = {}
    for i, part in enumerate(tradeprice.rstrip(',').split(','), 1):
        p = part.strip()
        if ':' in p:
            _, price = p.split(':', 1)
            prices[f'm{i}'] = price.strip()
        elif p:
            prices[f'm{i}'] = p
    if date and prices:
        row = {'date': date}
        row.update(prices)
        rows.append(row)

result = pd.DataFrame(rows)  # 框架自动按主键去重 upsert
```

创建该指标的命令：
```bash
python scripts/cli.py metrics create \
  --name "进口现货 LNG 到岸价格" \
  --code @lng_crawler.py \
  --pk-col date \
  --val-col m1 \
  --sort-col date \
  --unit "美元/百万英热单位" \
  --frequency 1d
```

```bash
# 新建指标（创建前自动验证代码正确性）
python scripts/cli.py metrics create \
  --name "广东现货均价" \
  --code @crawler.py \
  --pk-col date \
  --val-col value \
  --sort-col date \
  --unit "元/兆瓦时" \
  --frequency 1d \
  --metric-group-id 6   # 可选，指定指标组 ID；不填则放入「默认指标组」

# 更新指标（只更新提供的字段）
python scripts/cli.py metrics update <id> --name "新名称"
python scripts/cli.py metrics update <id> --code @new_crawler.py --val-col price
python scripts/cli.py metrics update <id> --metric-group-id 6  # 移动到其他指标组
python scripts/cli.py metrics update <id> --reset-schema       # 清除列结构，下次爬取重新初始化（修改了爬虫列定义时使用；Web UI 暂无此按钮）

# 删除指标
python scripts/cli.py metrics delete <id>
```

### 全局爬虫配置管理（仅 root 组）

全局配置是一个 JSON 字典，作为 `args` 注入所有爬虫代码。适合存放 API token、密钥、基础 URL 等。

```bash
# 查看当前全局配置
python scripts/cli.py metrics config

# 导出到文件
python scripts/cli.py metrics config -o config.json

# 整体替换配置（覆盖现有全部内容）
python scripts/cli.py metrics config-set '{"my_token": "<token值>", "api_key": "<key值>"}'
python scripts/cli.py metrics config-set @config.json  # 从文件读取

# 合并更新单个/多个键（不影响其他键）
python scripts/cli.py metrics config-update my_token=<新token值>
python scripts/cli.py metrics config-update api_key=<key值> base_url=https://api.example.com
```

### 通知公告

通知公告采用三层结构：**公告组 → 网站 → Tab**。
每个 Tab（即原「通知源」）对应一段爬虫代码，负责抓取一类通知文件。
`notices list` 的 ID 列对应 Tab（source）ID，可用于 `notices files` 和 `notices crawl`。

当前结构示例：
```
南方能源局（公告组）
  ├── 广东能源局（网站）
  │     └── 通知公告（Tab，ID=1）
  ├── 广西能源局（网站）
  │     └── 通知公告（Tab，ID=2）
  └── ...
```

```bash
# 查看所有可见通知 Tab（显示完整路径：公告组 > 网站 > Tab名）
python scripts/cli.py notices list

# 列出某 Tab 下的公告文件
python scripts/cli.py notices files <source_id>
python scripts/cli.py notices files <source_id> --search "光伏" --limit 20

# 下载某条公告 PDF 到本地
python scripts/cli.py notices get <source_id> <file_id>            # 默认以标题命名
python scripts/cli.py notices get <source_id> <file_id> -o doc.pdf # 指定路径

# 手动触发某 Tab 爬取（后台异步，不等待完成）
python scripts/cli.py notices crawl <id>
```

**典型工作流：**
```bash
# 1. 查看可用的通知 Tab
python scripts/cli.py notices list

# 2. 查找具体文件（可用关键词过滤）
python scripts/cli.py notices files 1 --search "绿证"

# 3. 下载 PDF（用 notices files 列出的 ID）
python scripts/cli.py notices get 1 <file_id> -o output.pdf
```

---

## 输出格式说明

- **`articles list`**：服务端分页，`--limit` 控制每页条数（默认 50），`--search` 按标题关键词搜索，`--date-from`/`--date-to`（YYYY-MM-DD）按发布时间过滤；每次返回第 1 页，若需更多数据请加大 `--limit` 或用 Web UI
- **`subscriptions list`**：显示 ID、名称、可见性、更新频率、PDF解析、最新文章时间
- **`hooks create`**：`--hook-type full`（默认）或 `judge_only`；`--judgment-prompt` 必填；`--action-prompt` 仅 `full` 类型必填，`judge_only` 不填；prompt 支持直接传字符串或 `@文件路径`（`@-` 读 stdin）；各 prompt 上限 1000 字符
- **`hooks update`**：只更新提供的字段；`--enable`/`--disable` 互斥
- **`hooks trigger`**：清除该 Hook 所有旧结果，对所有 `parse_status=completed` 文章重新执行
- **`hooks retry`**：清除该文章对应旧结果，对单篇文章重新执行
- **`articles batch-download`**：`-t md` 输出 `{标题}/{标题}.md + images/`；`-t pdf` 输出 `{标题}/{标题}.pdf`
- **`notices files`**：支持 `--search` 按标题关键词筛选，`--limit` 控制每页条数（默认 50）；`download_status=completed` 才可用 `notices get` 下载
- **`notices get`**：通过后端代理端点 `/api/notices/pdf?path=...` 流式下载，不暴露 MinIO 内网地址；`-o` 不指定时以公告标题命名文件；文件未下载完成（`pending`/`downloading`/`failed`）时报错退出
- **`notices crawl`**：爬取任务在后台异步运行，命令返回即表示已提交，不等待完成；用 `notices list` 观察文件数变化来确认是否完成
- **`metrics data`**：返回该指标所有历史数据点（时序），`-o file.csv` 导出 CSV（UTF-8 BOM），可直接用 Excel 或 pandas 打开
- **`metrics create`**：`--code` 支持直接传字符串或 `@文件路径`；创建前自动调用 `/validate` 试运行，失败则拒绝创建；root 组始终拥有访问权；爬虫代码必须将 `pandas.DataFrame` 赋给 `result`，返回 0 行视为失败
- **`metrics update`**：`--reset-schema` 清除已存储的列结构，下次爬取时重新初始化；修改了爬虫代码中的列定义后需配合此参数使用
- **`metrics config`**：返回 JSON 字典；`-o file.json` 导出文件
- **`metrics config-set`**：整体替换，传入的 JSON 成为新的全部配置
- **`metrics config-update`**：仅更新指定键，每个参数格式为 `key=value`
- **CSV 导出**（`hooks results -o`）：含 UTF-8 BOM，字段：文章ID、标题、状态、触发结果、执行时间、执行内容

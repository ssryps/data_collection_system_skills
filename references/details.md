# 权限、错误处理与 Web UI 说明

## 权限矩阵

| 操作 | admin | 组管理员 | 普通用户 |
|------|-------|---------|---------|
| subscriptions list | 全部 | 已订阅源 | 只读 |
| subscriptions add | ✓ | ✓（受订阅数上限约束） | ✗ |
| subscriptions check | ✓ | ✓（本组） | ✗ |
| hooks list / results  | ✓（全部） | ✓（本组 + root 组在公有源上的 Hook，只读） | ✓（本组 + root 组在公有源上的 Hook，只读） |
| hooks create / update / trigger / retry | ✓ | ✓（本组 Hook，root 组 Hook 只读不可操作） | ✗ |
| articles list | ✓ | ✓ | ✓（只读） |
| articles download / batch-download | ✓ | ✓ | ✓ |
| metrics list / data | ✓ | 取决于指标组可见性 | 取决于指标组可见性 |
| metrics run | ✓ | ✗ | ✗ |
| metrics create / update / delete | ✓ | ✗ | ✗ |
| metrics config / config-set / config-update | ✓ | ✗ | ✗ |
| triggers list / get / executions | ✓（全部组） | 组管理员 ✓（本组）；普通成员 ✓（只读） | 组管理员 ✓（本组）；普通成员 ✓（只读） |
| triggers create | ✓（任意可见资源） | ✓（组管理员，本组可见资源） | ✗ |
| triggers update / delete | ✓（全部触发器） | ✓（组管理员，本组触发器） | ✗ |
| notices list | ✓ | 取决于公告组可见性 | 取决于公告组可见性 |
| notices files | ✓ | 可见公告组内的源 | 可见公告组内的源 |
| notices get（下载 PDF） | ✓ | 可见公告组内的源 | 可见公告组内的源 |
| notices crawl | ✓ | ✗ | ✗ |

---

## 错误处理

| 错误 | 含义 | 处理 |
|------|------|------|
| `认证失败（401）` | Token 过期或无效 | 重新执行 `login` |
| `无法连接到服务器` | 服务未启动或地址错误 | 确认服务状态，或用 `--url` 指定地址 |
| `请求失败: 403` | 权限不足 | 换用有权限的账号，或联系管理员 |
| `subscriptions check` 返回失败 | API 瞬时抖动 | CLI 已内置 3 次自动重试（间隔 3 秒），三次全败再报错 |
| `已达到 Hook 数量上限` | 本组 Hook 数达到上限 | 上限由 admin 在用户组设置中配置；默认：普通组 3 个，付费组 15 个，admin 无限制 |
| `已达到私有源订阅上限` | 本组私有源数达到上限 | 默认：普通组 5 个，付费组 20 个；admin 可为特定组单独调高上限 |
| `该公众号是公开源，所有用户已可查看` | 尝试订阅一个已是公开源的公众号 | 公开源全员可见，无需订阅；直接在文章列表查看即可 |
| `公众号名称不匹配` | 填写的名称与文章实际作者不一致 | 重新确认公众号名称，名称须与微信文章中显示的作者名完全一致 |

---

## Web UI 功能补充说明

以下功能仅在浏览器 Web 界面操作，不通过 CLI：

| 功能 | 页面 | 权限 |
|------|------|------|
| 用户组自定义订阅/Hook 上限 | 用户管理 → 编辑用户组 | admin |
| 批量导入用户（CSV） | 用户管理 → 批量导入 | admin |
| 订阅源每次检查翻页上限（max_fetch_pages） | 订阅源管理 → 编辑订阅源 | admin |
| 指标组管理（新建/编辑/删除/设置可见性） | 指标监控 → 管理指标组 | admin |
| 将指标移动到其他组 | 指标监控 → 每个指标卡片的移动按钮 | admin |
| 公告组/网站/Tab 管理（新建/编辑/删除/设置可见性） | 通知公告 → 管理公告组 | admin |
| **触发器管理**（创建/编辑/删除/查看执行历史） | 侧边栏「触发器」（`/triggers.html`）或 CLI `triggers` 命令 | 所有登录用户可查看；组管理员或 root admin 可增删改 |
| **社交媒体帖子列表**（按平台/关键词/VL状态过滤，查看 VL 标注内容） | `/social.html` | 按集合可见性，admin 全量 |
| **社交媒体来源管理**（新建集合/来源，配置平台/关键词/频率/时间过滤/手动触发） | `/social_sources.html` | admin 管理，其他用户只读 |
| **社交媒体全局配置**（vLLM 地址、模型名、提示词模板） | 系统设置 → 社交媒体配置 | admin |
| Bug/建议反馈提交 | 侧边栏"Bug&建议" | 所有登录用户 |
| 查看/删除全部反馈 | 侧边栏"Bug&建议" | admin |

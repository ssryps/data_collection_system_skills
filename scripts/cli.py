#!/usr/bin/env python3
"""
数据收集服务 CLI
用法: python scripts/cli.py <command> [options]

支持的命令:
  check-auth              检查当前登录状态（token 是否有效），供大模型调用
  login                   登录系统，保存 token
  articles list           列出文章（服务端分页，支持 --source/--search/--date-from/--date-to/--limit）
  articles download <id>  下载单篇文章
  articles batch-download <id1,id2,...>  批量下载文章为 ZIP
  subscriptions list      列出订阅源
  subscriptions add       添加新订阅源（交互式引导，也可用 --name/--url/--pdf/--frequency 直接指定）
  subscriptions check <id>  手动检查更新
  hooks list <source_id>  列出某订阅源的 Hook
  hooks results <source_id> <hook_id>  获取 Hook 执行结果
  metrics list            列出指标
  metrics run <id>        手动触发指标爬取
  metrics data <id>       获取指标全部历史数据（可导出 CSV）
  metrics create          新建指标（仅 root 组，自动验证代码；可用 --metric-group-id 指定指标组）
  metrics update <id>     更新指标（仅 root 组；--metric-group-id 可将指标移至其他组）
  metrics delete <id>     删除指标（仅 root 组）
  metrics config          查看全局爬虫配置（仅 root 组）
  metrics config-set      整体替换全局爬虫配置（仅 root 组）
  metrics config-update   合并更新全局配置中的键（仅 root 组）
  notices list            列出通知公告源
  notices files <source_id>  列出某通知源下的公告文件（支持 --search/--limit）
  notices get <source_id> <file_id>  下载某条公告 PDF 到本地文件（-o 指定路径）
  notices crawl <id>      手动触发通知源爬取（后台异步）
  triggers list           列出可访问的触发器
  triggers get <id>       查看触发器详情（含代码）
  triggers create         创建触发器（--name/--event-type/--code 必填，支持 @文件路径）
  triggers update <id>    更新触发器配置（只更新提供的字段）
  triggers delete <id>    删除触发器及所有执行记录
  triggers executions <id>   列出触发器的执行历史
  triggers execution <exec_id>  查看单次执行详情（含输出/错误）
"""

import argparse
import os
import re
import sys
import subprocess
import json
import csv
import getpass
import io
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


def _ensure_deps():
    """检查并自动安装缺失的依赖包，无需手动 pip install。"""
    try:
        import requests  # noqa: F401
        return
    except ImportError:
        pass
    print("检测到缺失依赖 requests，正在自动安装...", file=sys.stderr)
    ret = subprocess.run(
        [sys.executable, "-m", "pip", "install", "requests", "-q"],
        capture_output=True, text=True
    )
    if ret.returncode != 0:
        print("自动安装失败，请手动运行: pip install requests", file=sys.stderr)
        if ret.stderr:
            print(ret.stderr, file=sys.stderr)
        sys.exit(1)
    print("requests 安装成功", file=sys.stderr)

_ensure_deps()
import requests

# 本地存储文件
TOKEN_FILE  = Path.home() / ".wechat_crawler_token"        # JWT Token
CREDS_FILE  = Path.home() / ".wechat_crawler_credentials"  # 登录凭证（用户名+密码）

# 服务器地址来源：优先 GitHub（快），失败后回退 Gitee（备用）
_IP_URLS = [
    "https://raw.githubusercontent.com/ssryps/data_collection_system_skills/main/ip_port.txt",
    "https://gitee.com/ssryps/data_collection_system_skills/raw/master/ip_port.txt",
]


def _fetch_server_url() -> str | None:
    """依次尝试各地址源，返回第一个成功读取的服务器 URL。
    ip_port.txt 格式：{"ip":"...","port":8000,"scheme":"http"}
    scheme 字段可选，缺省为 http。
    """
    import urllib.request
    for url in _IP_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wechat-cli/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
                scheme = data.get("scheme", "http")
                return f"{scheme}://{data['ip']}:{data['port']}"
        except Exception:
            continue
    return None




_CREDS_PLACEHOLDER = {"username": "请填写用户名", "password": "请填写密码"}


def save_credentials(username: str, password: str):
    """将登录凭证保存到本地（仅本用户可读），供 check-auth 自动续期使用。"""
    CREDS_FILE.write_text(
        json.dumps({"username": username, "password": password}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    try:
        CREDS_FILE.chmod(0o600)
    except Exception:
        pass  # Windows 不支持 chmod，忽略


def load_credentials() -> Optional[dict]:
    """读取本地保存的登录凭证，未保存时返回 None。"""
    if CREDS_FILE.exists():
        try:
            return json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _create_creds_template():
    """创建凭证模板文件供用户填写，已存在则不覆盖。"""
    if not CREDS_FILE.exists():
        CREDS_FILE.write_text(
            json.dumps(_CREDS_PLACEHOLDER, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        try:
            CREDS_FILE.chmod(0o600)
        except Exception:
            pass


def _is_filled(creds: dict) -> bool:
    """判断凭证是否已实际填写（非占位符、非空）。"""
    return (
        bool(creds.get("username")) and
        bool(creds.get("password")) and
        creds.get("username") != _CREDS_PLACEHOLDER["username"] and
        creds.get("password") != _CREDS_PLACEHOLDER["password"]
    )


def load_token() -> Optional[str]:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return None


def save_token(token: str):
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)


def get_headers(token: Optional[str] = None) -> dict:
    t = token or load_token()
    if t:
        return {"Authorization": f"Bearer {t}"}
    return {}


def api_get(base_url: str, path: str, params: dict = None) -> dict:
    resp = requests.get(f"{base_url}{path}", headers=get_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def api_post(base_url: str, path: str, data: dict = None) -> dict:
    resp = requests.post(f"{base_url}{path}", headers=get_headers(), json=data, timeout=60)
    resp.raise_for_status()
    return resp.json()


def api_post_binary(base_url: str, path: str, data: dict = None) -> bytes:
    resp = requests.post(f"{base_url}{path}", headers=get_headers(), json=data, timeout=120)
    resp.raise_for_status()
    return resp.content


def api_put(base_url: str, path: str, data: dict = None) -> dict:
    resp = requests.put(f"{base_url}{path}", headers=get_headers(), json=data, timeout=60)
    resp.raise_for_status()
    return resp.json()


def api_delete(base_url: str, path: str) -> dict:
    resp = requests.delete(f"{base_url}{path}", headers=get_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _read_content(value: str) -> str:
    """支持 @文件路径 语法读取文件内容，否则直接返回字符串"""
    if value and value.startswith("@"):
        path = value[1:]
        if path == "-":
            return sys.stdin.read()
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
    return value


def print_table(rows: list, headers: list):
    """打印简单文本表格"""
    if not rows:
        print("(无数据)")
        return
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("  ".join("-" * w for w in col_widths))
    for row in rows:
        print(fmt.format(*[str(c) for c in row]))


# ── 命令实现 ────────────────────────────────────────────────

def _fail(result: dict):
    """打印失败原因并退出。优先显示 detail/message，否则输出原始响应。"""
    detail = result.get("detail") or result.get("message") or ""
    if detail:
        print(f"失败: {detail}", file=sys.stderr)
    else:
        print(f"失败: 服务器返回未知错误，原始响应: {result}", file=sys.stderr)
    sys.exit(1)


def _auto_login(config: dict) -> bool:
    """用本地保存的凭证静默重新登录，成功返回 True 并更新 token，失败返回 False。"""
    creds = load_credentials()
    if not creds or not _is_filled(creds):
        return False
    try:
        resp = requests.post(
            f"{config['base_url']}/api/auth/login",
            json={"username": creds["username"], "password": creds["password"]},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("success"):
            save_token(result["data"]["access_token"])
            return True
    except Exception:
        pass
    return False


def _prompt_fill_creds():
    """创建凭证模板文件并输出引导信息，让用户直接编辑文件而无需输入命令。"""
    _create_creds_template()
    print("NEED_CREDENTIALS", file=sys.stderr)
    print(str(CREDS_FILE), file=sys.stderr)


def cmd_check_auth(args, config: dict):
    """检查当前 token 是否有效；Token 失效时自动用保存的凭证续期。
    若凭证文件尚未填写，输出文件路径并以 exit 1 退出，由 AI 助手转告用户填写。
    """
    token = load_token()

    if not token:
        if _auto_login(config):
            print("已自动重新登录")
            return
        _prompt_fill_creds()
        sys.exit(1)

    try:
        resp = requests.get(
            f"{config['base_url']}/api/articles",
            headers={"Authorization": f"Bearer {token}"},
            params={"page_size": 1},
            timeout=10,
        )
        if resp.status_code == 401:
            if _auto_login(config):
                print("Token 已自动刷新，已重新登录")
                return
            _prompt_fill_creds()
            sys.exit(1)
        resp.raise_for_status()
        print("已登录")
    except requests.exceptions.ConnectionError:
        print(f"无法连接到服务器: {config['base_url']}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"检查登录状态失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_login(args, config: dict):
    username = getattr(args, "username", None) or input("用户名: ")
    password = getattr(args, "password", None) or getpass.getpass("密码: ")
    resp = requests.post(
        f"{config['base_url']}/api/auth/login",
        json={"username": username, "password": password},
        timeout=10
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("success"):
        token = result["data"]["access_token"]
        save_token(token)
        save_credentials(username, password)
        user = result["data"]["user"]
        print(f"登录成功，用户: {user['username']}（角色: {user['role']}，用户组: {user['group_name']}）")
    else:
        print(f"登录失败: {result.get('detail', '未知错误')}", file=sys.stderr)
        sys.exit(1)


def cmd_setup(args, config: dict):
    """首次使用初始化：交互式输入用户名和密码，保存凭证到本地，并完成初次登录验证。
    凭证保存后，check-auth 可自动续期 Token，无需再次输入密码。
    """
    print("=== 数据收集服务 CLI 初始化 ===")
    print(f"凭证将保存至 {CREDS_FILE}（仅本用户可读，不会传递给 AI 助手）")
    print()
    username = input("用户名: ").strip()
    if not username:
        print("用户名不能为空", file=sys.stderr)
        sys.exit(1)
    password = getpass.getpass("密码: ")
    if not password:
        print("密码不能为空", file=sys.stderr)
        sys.exit(1)

    print("正在验证凭证...")
    try:
        resp = requests.post(
            f"{config['base_url']}/api/auth/login",
            json={"username": username, "password": password},
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.ConnectionError:
        print(f"无法连接到服务器: {config['base_url']}", file=sys.stderr)
        print("请确认服务已启动，或使用 --url 指定正确地址后重试", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"登录请求失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not result.get("success"):
        print(f"登录失败: {result.get('detail', '用户名或密码错误')}", file=sys.stderr)
        sys.exit(1)

    save_credentials(username, password)
    save_token(result["data"]["access_token"])
    user = result["data"]["user"]
    print(f"初始化完成！已登录为: {user['username']}（角色: {user['role']}，用户组: {user['group_name']}）")
    print("后续无需重复操作，Token 过期时将自动刷新。")


def cmd_articles_list(args, config: dict):
    params = {"page": 1, "page_size": args.limit or 50}
    if args.source:
        params["source_id"] = args.source
    if args.search:
        params["search"] = args.search
    if args.date_from:
        params["date_from"] = args.date_from
    if args.date_to:
        params["date_to"] = args.date_to
    result = api_get(config["base_url"], "/api/articles", params)
    articles = result["data"]["articles"]
    rows = [
        (a["id"], a["title"][:40], a["source_name"] or "-",
         a["publish_time"] or "-", a["download_status"], a["parse_status"])
        for a in articles
    ]
    print_table(rows, ["ID", "标题", "订阅源", "发布时间", "下载状态", "解析状态"])
    print(f"\n共 {result['data']['total']} 篇（显示 {len(articles)} 篇）")


def cmd_articles_download(args, config: dict):
    result = api_post(config["base_url"], "/api/articles/download", {"article_id": args.id})
    if result.get("success"):
        print(f"已加入下载队列: {result.get('message', '')}")
    else:
        _fail(result)


def cmd_articles_batch_download(args, config: dict):
    ids = [int(i.strip()) for i in args.ids.split(",") if i.strip()]
    if not ids:
        print("请提供文章 ID 列表，用逗号分隔", file=sys.stderr)
        sys.exit(1)
    download_type = args.type or "md"
    print(f"正在打包 {len(ids)} 篇文章（类型: {download_type}）...")
    content = api_post_binary(
        config["base_url"],
        "/api/articles/batch-download",
        {"article_ids": ids, "download_type": download_type}
    )
    out_path = args.output or "articles.zip"
    Path(out_path).write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = z.namelist()
    print(f"已保存到 {out_path}，包含 {len(names)} 个文件:")
    for n in names:
        print(f"  {n}")


def cmd_subscriptions_list(args, config: dict):
    result = api_get(config["base_url"], "/api/subscriptions")
    sources = result["data"]
    rows = []
    for s in sources:
        # 获取调度频率：优先取当前用户组的订阅（my_subscription），
        # 其次取 schedule_options（对自己组可见的调度），
        # 最后遍历 all_user_subs（admin 视角可见所有组）
        my_sub = s.get("my_subscription") or {}
        schedule_opts = s.get("schedule_options") or []
        all_subs = s.get("all_user_subs") or []

        if my_sub:
            freq = my_sub.get("check_frequency", "-")
        elif schedule_opts:
            freq = schedule_opts[0].get("frequency", "-")
        elif all_subs:
            # admin 视角：显示所有组频率汇总（去重）
            freqs = list(dict.fromkeys(
                sub.get("check_frequency", "-") for sub in all_subs
            ))
            freq = "/".join(freqs) if freqs else "-"
        else:
            freq = "-"

        last_time = (s.get("last_article_time") or "-")[:16]  # 截到分钟
        # source_type 已包含公有/私有及订阅组数信息，直接用作"可见性"列
        visibility = s.get("source_type") or ("公有源" if s["is_public"] else "私有源")
        rows.append((
            s["id"],
            s["name"],
            visibility,
            freq,
            "是" if s.get("pdf_parse_enabled") else "否",
            last_time,
        ))
    print_table(rows, ["ID", "名称", "可见性", "更新频率", "PDF解析", "最新文章时间"])


_FREQ_LABELS = {
    "none": "不自动更新",
    "12h":  "每 12 小时",
    "1d":   "每天",
    "2d":   "每 2 天",
    "7d":   "每 7 天",
}


def cmd_subscriptions_add(args, config: dict):
    """添加新订阅源（交互式）"""
    # ── 公众号名称 ──────────────────────────────────────
    name = getattr(args, "name", None) or ""
    if not name:
        name = input("公众号名称（需与文章作者名称完全一致）: ").strip()
    if not name:
        print("名称不能为空", file=sys.stderr)
        sys.exit(1)

    # ── 文章地址 ────────────────────────────────────────
    url = getattr(args, "article_url", None) or ""
    if not url:
        url = input("该公众号发布的任意一篇文章地址（用于识别公众号 ID）: ").strip()
    if not url:
        print("文章地址不能为空", file=sys.stderr)
        sys.exit(1)

    # ── PDF 解析 ────────────────────────────────────────
    if getattr(args, "pdf", None):
        enable_pdf = True
    elif getattr(args, "no_pdf", None):
        enable_pdf = False
    else:
        ans = input("是否开启 PDF 解析（将文章转为 Markdown，便于 AI 读取）？[y/N] ").strip().lower()
        enable_pdf = ans in ("y", "yes", "是")

    # ── 更新频率 ────────────────────────────────────────
    freq = getattr(args, "frequency", None)
    if freq and freq not in _FREQ_LABELS:
        print(f"不支持的频率 '{freq}'，支持值：{', '.join(_FREQ_LABELS.keys())}", file=sys.stderr)
        sys.exit(1)
    if not freq:
        print("更新频率选项：")
        for i, (k, label) in enumerate(_FREQ_LABELS.items(), 1):
            print(f"  {i}. {k:4s}  {label}")
        while True:
            choice = input("请输入序号或频率代码（默认 none）: ").strip() or "none"
            if choice.isdigit():
                idx = int(choice) - 1
                keys = list(_FREQ_LABELS.keys())
                if 0 <= idx < len(keys):
                    freq = keys[idx]
                    break
                print("序号超出范围，请重试")
            elif choice in _FREQ_LABELS:
                freq = choice
                break
            else:
                print(f"无效输入，支持值：{', '.join(_FREQ_LABELS.keys())}")

    # ── 首次检查时间（仅在设置了周期性频率时收集）──────────
    check_time = getattr(args, "check_time", None) or None
    if freq != "none" and not check_time:
        default_time = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
        raw = input(f"首次检查时间（YYYY-MM-DDTHH:MM，留空默认当前时间+5分钟 {default_time}）: ").strip()
        if raw:
            if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", raw):
                print("时间格式不正确，应为 YYYY-MM-DDTHH:MM，如 2026-04-27T08:00", file=sys.stderr)
                sys.exit(1)
            check_time = raw
        else:
            check_time = default_time

    # ── 确认并提交 ──────────────────────────────────────
    print(f"\n即将添加订阅源：")
    print(f"  公众号名称 : {name}")
    print(f"  文章地址   : {url}")
    print(f"  PDF 解析   : {'开启' if enable_pdf else '关闭'}")
    print(f"  更新频率   : {_FREQ_LABELS[freq]} ({freq})")
    if check_time:
        print(f"  首次检查时间: {check_time}")
    confirm = input("确认添加？[Y/n] ").strip().lower()
    if confirm in ("n", "no", "否"):
        print("已取消")
        return

    payload = {
        "name": name,
        "article_url": url,
        "enable_pdf_parse": enable_pdf,
        "check_frequency": freq,
        "check_time": check_time,
    }
    print("正在添加，请稍候（后端将调用 TikHub API 验证公众号信息）...")
    result = api_post(config["base_url"], "/api/subscriptions", payload)
    if result.get("success"):
        d = result["data"]
        action = d.get("action", "")
        if action == "created":
            print(f"添加成功！订阅源 ID={d['id']}，ghid={d.get('ghid', '-')}（新建）")
            print("后台正在拉取历史文章，稍后可用 articles list 查看")
        elif action == "subscribed":
            print(f"订阅成功！该公众号已有订阅源 ID={d['id']}，已加入本组订阅")
        else:
            print(f"操作成功：{d}")
    else:
        _fail(result)


def cmd_subscriptions_check(args, config: dict):
    # subscriptions check 依赖 TikHub 外部 API，该 API 偶尔出现瞬时失败（限流、服务抖动）。
    # 遇到 success=false 时最多自动重试 2 次，每次间隔 3 秒，三次全败才报错。
    MAX_ATTEMPTS = 3
    last_result = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        last_result = api_post(config["base_url"], f"/api/subscriptions/{args.id}/check")
        if last_result.get("success"):
            data = last_result.get("data", {})
            added = data.get("added", 0)
            msg = last_result.get("message", "")
            print(f"检查完成: 新增 {added} 篇文章" + (f"（{msg}）" if msg else ""))
            return
        detail = last_result.get("detail") or last_result.get("message") or ""
        if attempt < MAX_ATTEMPTS:
            print(f"第 {attempt} 次尝试失败（{detail}），3 秒后重试...", file=sys.stderr)
            import time; time.sleep(3)
    _fail(last_result)


def _read_prompt(value: str) -> str:
    """读取 prompt 内容：若以 @ 开头则读取文件，否则直接返回字符串"""
    if value.startswith("@"):
        path = value[1:]
        if path == "-":
            return sys.stdin.read()
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"文件不存在: {path}", file=sys.stderr)
            sys.exit(1)
    return value


def cmd_hooks_list(args, config: dict):
    result = api_get(config["base_url"], f"/api/subscriptions/{args.source_id}/hooks")
    hooks = result["data"]
    if not hooks:
        print("该订阅源暂无 Hook（或当前用户无权限查看）")
        return
    rows = [(h["id"], h["name"], "启用" if h["is_active"] else "禁用",
             (h.get("description") or "-")[:40]) for h in hooks]
    print_table(rows, ["ID", "名称", "状态", "描述"])


def cmd_hooks_create(args, config: dict):
    hook_type = getattr(args, "hook_type", "full") or "full"
    if hook_type == "full" and not args.action_prompt:
        print("错误：full 类型 Hook 必须提供 --action-prompt", file=sys.stderr)
        sys.exit(1)
    judgment_prompt = _read_prompt(args.judgment_prompt)
    action_prompt = _read_prompt(args.action_prompt) if args.action_prompt else None
    payload = {
        "name": args.name,
        "hook_type": hook_type,
        "judgment_prompt": judgment_prompt,
        "action_prompt": action_prompt,
        "is_active": not args.disabled,
    }
    if args.description:
        payload["description"] = args.description
    result = api_post(config["base_url"], f"/api/subscriptions/{args.source_id}/hooks", payload)
    if result.get("success"):
        d = result["data"]
        type_label = "仅判断" if d.get("hook_type") == "judge_only" else "完整"
        print(f"Hook 创建成功: id={d['id']}  名称={d['name']}  类型={type_label}  状态={'启用' if d['is_active'] else '禁用'}")
    else:
        _fail(result)


def cmd_hooks_update(args, config: dict):
    payload = {}
    if args.name is not None:
        payload["name"] = args.name
    if args.description is not None:
        payload["description"] = args.description
    if args.judgment_prompt is not None:
        payload["judgment_prompt"] = _read_prompt(args.judgment_prompt)
    if args.action_prompt is not None:
        payload["action_prompt"] = _read_prompt(args.action_prompt)
    if args.enable:
        payload["is_active"] = True
    elif args.disable:
        payload["is_active"] = False

    if not payload:
        print("未提供任何要更新的字段", file=sys.stderr)
        sys.exit(1)

    result = api_post.__wrapped__ if hasattr(api_post, "__wrapped__") else None
    resp = requests.put(
        f"{config['base_url']}/api/subscriptions/{args.source_id}/hooks/{args.hook_id}",
        headers=get_headers(),
        json=payload,
        timeout=30
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("success"):
        d = result["data"]
        print(f"Hook 更新成功: id={d['id']}  名称={d['name']}  状态={'启用' if d['is_active'] else '禁用'}")
        if d.get("judgment_prompt"):
            print(f"  判断Prompt: {d['judgment_prompt'][:60]}{'...' if len(d['judgment_prompt']) > 60 else ''}")
        if d.get("action_prompt"):
            print(f"  操作Prompt: {d['action_prompt'][:60]}{'...' if len(d['action_prompt']) > 60 else ''}")
    else:
        _fail(result)


def cmd_hooks_trigger(args, config: dict):
    result = api_post(config["base_url"],
                      f"/api/subscriptions/{args.source_id}/hooks/{args.hook_id}/trigger")
    if result.get("success"):
        d = result.get("data", {})
        print(f"已触发: 共 {d.get('triggered_count', 0)} 篇文章加入执行队列"
              f"（清除了 {d.get('deleted_count', 0)} 条旧结果）")
    else:
        _fail(result)


def cmd_hooks_retry(args, config: dict):
    result = api_post(config["base_url"],
                      f"/api/articles/{args.article_id}/hooks/{args.hook_id}/retry")
    if result.get("success"):
        print(f"已重新触发: 文章 {args.article_id} × Hook {args.hook_id}")
    else:
        _fail(result)


def cmd_hooks_results(args, config: dict):
    result = api_get(config["base_url"],
                     f"/api/subscriptions/{args.source_id}/hooks/{args.hook_id}/results")
    results = result["data"]
    if args.output:
        # 导出 CSV
        with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["文章ID", "文章标题", "状态", "触发结果", "执行时间", "执行内容"])
            for r in results:
                writer.writerow([
                    r["article_id"], r["article_title"], r["status"],
                    r["judgment_result"], r["created_at"], r["result_content"]
                ])
        print(f"已导出 {len(results)} 条结果到 {args.output}")
    else:
        rows = [(r["article_id"], r["article_title"][:40], r["status"],
                 r["judgment_result"] or "-", r["created_at"] or "-") for r in results]
        print_table(rows, ["文章ID", "标题", "状态", "触发结果", "执行时间"])
        print(f"\n共 {len(results)} 条")


def cmd_metrics_list(args, config: dict):
    result = api_get(config["base_url"], "/api/metrics")
    metrics = result["data"]
    rows = []
    for m in metrics:
        lr = (m.get("latest_result") or {}).get("data") or {}
        latest_val = lr.get("latest_value", "-")
        latest_date = lr.get("latest_key", "-")
        rows.append((
            m["id"], m["name"], m.get("unit", "-"),
            latest_val, latest_date,
            (m.get("last_check_at") or "-")[:16],
        ))
    print_table(rows, ["ID", "名称", "单位", "最新值", "最新日期", "最后检查时间"])


def cmd_metrics_run(args, config: dict):
    result = api_post(config["base_url"], f"/api/metrics/{args.id}/run")
    if result.get("success"):
        data = result.get("data", {})
        print(f"已触发爬取" + (f": {data.get('message', '')}" if data.get("message") else ""))
    else:
        _fail(result)


def cmd_metrics_data(args, config: dict):
    result = api_get(config["base_url"], f"/api/metrics/{args.id}/data")
    data = result["data"]
    rows = data.get("rows", [])
    columns = data.get("columns", [])
    total = data.get("total", len(rows))
    unit = data.get("unit", "")

    if not rows:
        print("该指标暂无历史数据")
        return

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                if isinstance(row, dict):
                    writer.writerow([row.get(c, "") for c in columns])
                else:
                    writer.writerow(row)
        print(f"已导出 {total} 条历史数据到 {args.output}（单位: {unit or '未知'}）")
    else:
        # 终端打印：显示全部列
        if columns and rows:
            # 为主值列加单位标注
            val_col = data.get("val_col", "")
            headers = [f"{c}（{unit}）" if c == val_col and unit else c for c in columns]
            if isinstance(rows[0], dict):
                display_rows = [tuple(str(r.get(c, "-")) for c in columns) for r in rows]
            else:
                display_rows = [tuple(str(v) for v in r) for r in rows]
            print_table(display_rows, headers)
        if rows:
            pk = data.get("pk_col", "date")
            all_keys = [r.get(pk, "") if isinstance(r, dict) else "" for r in rows]
            all_keys = sorted(k for k in all_keys if k)
            range_hint = f"，时间范围 {all_keys[0]} ~ {all_keys[-1]}" if all_keys else ""
        else:
            range_hint = ""
        print(f"\n共 {total} 条记录{range_hint}，单位: {unit or '未知'}")


def cmd_metrics_create(args, config: dict):
    """新建指标（仅 root 组）。创建前会自动试运行代码验证正确性。"""
    code = _read_content(args.code)
    pk_col   = args.pk_col.strip()
    val_col  = args.val_col.strip()
    sort_col = args.sort_col.strip()

    # 先验证代码
    print("正在试运行代码验证...")
    try:
        v = api_post(config["base_url"], "/api/metrics/validate", {
            "code": code,
            "primary_key_col": pk_col,
            "main_value_col": val_col,
            "sort_col": sort_col,
        })
    except Exception as e:
        print(f"验证请求失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not v.get("success"):
        print(f"代码验证失败: {v.get('message', v)}", file=sys.stderr)
        sys.exit(1)
    print(f"验证通过: {v['message']}")

    # 创建指标
    payload = {
        "name":            args.name,
        "code":            code,
        "primary_key_col": pk_col,
        "main_value_col":  val_col,
        "sort_col":        sort_col,
        "unit":            args.unit or None,
        "description":     args.description or None,
        "check_frequency": args.frequency,
        "check_time":      args.check_time or None,
    }
    if args.metric_group_id is not None:
        payload["metric_group_id"] = args.metric_group_id
    result = api_post(config["base_url"], "/api/metrics", payload)
    if result.get("success"):
        m = result["data"]
        print(f"创建成功，ID={m['id']}，名称={m['name']}")
    else:
        _fail(result)


def cmd_metrics_update(args, config: dict):
    """更新指标（仅 root 组）。只更新提供的字段。"""
    payload = {}
    if args.name        is not None: payload["name"]            = args.name
    if args.description is not None: payload["description"]     = args.description
    if args.unit        is not None: payload["unit"]            = args.unit
    if args.pk_col      is not None: payload["primary_key_col"] = args.pk_col.strip()
    if args.val_col     is not None: payload["main_value_col"]  = args.val_col.strip()
    if args.sort_col    is not None: payload["sort_col"]        = args.sort_col.strip()
    if args.frequency   is not None: payload["check_frequency"] = args.frequency
    if args.check_time  is not None: payload["check_time"]      = args.check_time
    if args.code              is not None: payload["code"]            = _read_content(args.code)
    if args.metric_group_id   is not None: payload["metric_group_id"] = args.metric_group_id

    if not payload:
        print("未提供任何要更新的字段", file=sys.stderr)
        sys.exit(1)

    result = api_put(config["base_url"], f"/api/metrics/{args.id}", payload)
    if result.get("success"):
        print(f"更新成功")
    else:
        _fail(result)


def cmd_metrics_delete(args, config: dict):
    """删除指标（仅 root 组）。"""
    result = api_delete(config["base_url"], f"/api/metrics/{args.id}")
    if result.get("success"):
        print("删除成功")
    else:
        _fail(result)


def cmd_metrics_config_get(args, config: dict):
    """查看指标爬虫全局配置（仅 root 组）。"""
    result = api_get(config["base_url"], "/api/metrics/config")
    cfg = result.get("data", {})
    if args.output:
        Path(args.output).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出到 {args.output}")
    else:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))


def cmd_metrics_config_set(args, config: dict):
    """设置指标爬虫全局配置（仅 root 组）。整体替换为提供的 JSON。"""
    raw = _read_content(args.json_value)
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(cfg, dict):
        print("配置必须是 JSON 对象 {...}", file=sys.stderr)
        sys.exit(1)
    result = api_put(config["base_url"], "/api/metrics/config", {"config": cfg})
    if result.get("success"):
        print(f"全局配置已更新（共 {len(cfg)} 个键）")
    else:
        _fail(result)


def cmd_metrics_config_update(args, config: dict):
    """向全局配置中合并/更新单个或多个键（不影响其他键）。"""
    # 先读取现有配置
    existing = api_get(config["base_url"], "/api/metrics/config").get("data", {})
    # 合并
    for kv in args.set:
        if "=" not in kv:
            print(f"格式错误（应为 key=value）: {kv}", file=sys.stderr)
            sys.exit(1)
        k, v = kv.split("=", 1)
        existing[k.strip()] = v.strip()
    result = api_put(config["base_url"], "/api/metrics/config", {"config": existing})
    if result.get("success"):
        print(f"已更新，当前共 {len(existing)} 个键")
    else:
        _fail(result)


def cmd_notices_list(args, config: dict):
    result = api_get(config["base_url"], "/api/notices")
    notices = result["data"]
    rows = [(
        n["id"],
        # 路径：公告组 > 网站 > Tab
        " > ".join(filter(None, [
            n.get("notice_collection_name"),
            n.get("notice_site_name"),
            n.get("name"),
        ])) or n.get("name", "-"),
        n.get("crawl_frequency", "-"),
        (n.get("last_crawl_at") or "-")[:16],
        n.get("file_count", "-"),
    ) for n in notices]
    print_table(rows, ["ID", "路径（公告组 > 网站 > Tab）", "爬取频率", "最后爬取时间", "文件数"])


def cmd_notices_crawl(args, config: dict):
    result = api_post(config["base_url"], f"/api/notices/{args.id}/run")
    if result.get("success"):
        msg = result.get("message", "已启动爬取任务")
        print(f"爬取任务已启动：{msg}")
        print("（爬取在后台进行，请稍后用 notices list 查看文件数变化）")
    else:
        _fail(result)


def cmd_notices_files(args, config: dict):
    """列出某通知源下的公告文件列表"""
    params = {"page": 1, "page_size": args.limit or 50}
    if args.search:
        params["keyword"] = args.search
    result = api_get(config["base_url"], f"/api/notices/{args.source_id}/files", params)
    data = result["data"]
    files = data["files"]
    if not files:
        print("（暂无文件）")
        return
    rows = [(
        f["id"],
        f["title"][:50],
        f.get("publish_time") or "-",
        f["download_status"],
    ) for f in files]
    print_table(rows, ["ID", "标题", "发布时间", "下载状态"])
    print(f"\n共 {data['total']} 个文件（显示 {len(files)} 个）")


def cmd_notices_get(args, config: dict):
    """下载某条通知公告 PDF 到本地文件"""
    # 先查找该 file_id 对应的记录，拿到 file_path 和 title
    # 遍历文件列表找到匹配的 ID（API 无单条查询端点）
    result = api_get(config["base_url"], f"/api/notices/{args.source_id}/files",
                     {"page": 1, "page_size": 0})
    files = result["data"]["files"]
    target = next((f for f in files if f["id"] == args.file_id), None)
    if target is None:
        print(f"未找到文件 ID={args.file_id}（请确认 source_id 和 file_id 是否正确）",
              file=sys.stderr)
        sys.exit(1)

    file_path = target.get("file_path")
    if not file_path:
        print(f"该文件尚未下载完成（download_status={target['download_status']}）",
              file=sys.stderr)
        sys.exit(1)

    # 通过后端代理端点流式下载 PDF
    import urllib.parse
    url = f"{config['base_url']}/api/notices/pdf?path={urllib.parse.quote(file_path, safe='/')}"
    resp = requests.get(url, headers=get_headers(), timeout=60, stream=True)
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        print(f"下载失败（{resp.status_code}）：{detail}", file=sys.stderr)
        sys.exit(1)

    # 确定输出路径
    title_safe = re.sub(r'[<>:"/\\|?*\n\r]', '_', target["title"]).strip() or f"notice_{args.file_id}"
    out_path = args.output or f"{title_safe}.pdf"
    with open(out_path, "wb") as fout:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                fout.write(chunk)
    size_kb = Path(out_path).stat().st_size // 1024
    print(f"已保存：{out_path}（{size_kb} KB）")


# ── 触发器命令 ──────────────────────────────────────────────

def cmd_triggers_list(args, config: dict):
    result = api_get(config["base_url"], "/api/triggers")
    triggers = result.get("data", [])
    if not triggers:
        print("暂无触发器")
        return
    rows = []
    for t in triggers:
        scope_parts = []
        if t.get("source_name"):  scope_parts.append(f"源:{t['source_name'][:12]}")
        if t.get("hook_name"):    scope_parts.append(f"Hook:{t['hook_name'][:10]}")
        if t.get("metric_name"):  scope_parts.append(f"指标:{t['metric_name'][:10]}")
        scope = " ".join(scope_parts) or "所有"
        group = t.get("group_name") or "全局"
        rows.append((
            t["id"],
            t["name"][:25],
            t["event_type"],
            scope,
            "启用" if t["is_active"] else "禁用",
            group,
        ))
    print_table(rows, ["ID", "名称", "事件类型", "Scope", "状态", "用户组"])
    print(f"\n共 {len(triggers)} 个触发器")


def cmd_triggers_get(args, config: dict):
    result = api_get(config["base_url"], f"/api/triggers/{args.id}")
    t = result["data"]
    print(f"ID:       {t['id']}")
    print(f"名称:     {t['name']}")
    print(f"描述:     {t.get('description') or '-'}")
    print(f"事件类型: {t['event_type']}  ({t.get('event_type_label', '')})")
    print(f"用户组:   {t.get('group_name') or '全局'}")
    print(f"超时:     {t.get('timeout', 60)} 秒")
    print(f"状态:     {'启用' if t['is_active'] else '禁用'}")
    if t.get("source_name"):       print(f"订阅源:   {t['source_name']} (#{t['source_id']})")
    if t.get("hook_name"):         print(f"Hook:     {t['hook_name']} (#{t['hook_id']})")
    if t.get("metric_name"):       print(f"指标:     {t['metric_name']} (#{t['metric_id']})")
    if t.get("notice_source_name"): print(f"通知源:   {t['notice_source_name']} (#{t['notice_source_id']})")
    print(f"创建时间: {t.get('created_at', '')}")
    print(f"更新时间: {t.get('updated_at', '')}")
    print(f"\n── 执行代码 ──\n{t['code']}")


def cmd_triggers_create(args, config: dict):
    payload = {
        "name":       args.name,
        "event_type": args.event_type,
        "code":       _read_content(args.code),
        "timeout":    args.timeout,
        "is_active":  not args.disabled,
    }
    if args.description:      payload["description"]      = args.description
    if args.source_id:        payload["source_id"]        = args.source_id
    if args.hook_id:          payload["hook_id"]          = args.hook_id
    if args.metric_id:        payload["metric_id"]        = args.metric_id
    if args.notice_source_id: payload["notice_source_id"] = args.notice_source_id
    result = api_post(config["base_url"], "/api/triggers", payload)
    if result.get("success"):
        d = result["data"]
        print(f"触发器创建成功: id={d['id']}  名称={d['name']}  事件={d['event_type']}  状态={'启用' if d['is_active'] else '禁用'}")
    else:
        _fail(result)


def cmd_triggers_update(args, config: dict):
    payload = {}
    if args.name is not None:        payload["name"]        = args.name
    if args.description is not None: payload["description"] = args.description
    if args.event_type is not None:  payload["event_type"]  = args.event_type
    if args.code is not None:        payload["code"]        = _read_content(args.code)
    if args.timeout is not None:     payload["timeout"]     = args.timeout
    if args.source_id is not None:   payload["source_id"]   = args.source_id
    if args.hook_id is not None:     payload["hook_id"]     = args.hook_id
    if args.metric_id is not None:   payload["metric_id"]   = args.metric_id
    if args.enable:   payload["is_active"] = True
    if args.disable:  payload["is_active"] = False
    if not payload:
        print("未提供任何要更新的字段", file=sys.stderr)
        sys.exit(1)
    resp = requests.put(f"{config['base_url']}/api/triggers/{args.id}",
                        headers=get_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if result.get("success"):
        d = result["data"]
        print(f"更新成功: id={d['id']}  名称={d['name']}  状态={'启用' if d['is_active'] else '禁用'}")
    else:
        _fail(result)


def cmd_triggers_delete(args, config: dict):
    if not args.yes:
        confirm = input(f"确定删除触发器 id={args.id} 及其所有执行记录？(y/N) ").strip().lower()
        if confirm != 'y':
            print("已取消")
            return
    resp = requests.delete(f"{config['base_url']}/api/triggers/{args.id}",
                           headers=get_headers(), timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if result.get("success"):
        print(f"触发器 id={args.id} 已删除")
    else:
        _fail(result)



def cmd_triggers_executions(args, config: dict):
    params = {"limit": args.limit}
    result = api_get(config["base_url"], f"/api/triggers/{args.id}/executions", params)
    execs = result.get("data", [])
    if not execs:
        print("暂无执行记录")
        return
    rows = []
    for e in execs:
        run_res = ""
        if e.get("event_data") and isinstance(e["event_data"], dict):
            run_res = e["event_data"].get("run_result", "")
        rows.append((
            e["id"],
            e.get("created_at", "")[:16],
            e["event_type"],
            run_res,
            e["status"],
            e.get("duration") or "-",
            (e.get("error") or "")[:40],
        ))
    print_table(rows, ["执行ID", "时间", "事件类型", "运行结果", "状态", "耗时", "错误"])
    print(f"\n共 {len(execs)} 条（最近 {args.limit}）")


def cmd_triggers_execution(args, config: dict):
    result = api_get(config["base_url"], f"/api/triggers/executions/{args.exec_id}")
    e = result["data"]
    print(f"执行 ID:  {e['id']}")
    print(f"触发器:   #{e['trigger_id']}")
    print(f"事件类型: {e['event_type']}")
    print(f"状态:     {e['status']}")
    print(f"耗时:     {e.get('duration') or '-'}")
    print(f"时间:     {e.get('created_at', '')}")
    if e.get("event_data"):
        print(f"\n── 事件数据 ──\n{json.dumps(e['event_data'], ensure_ascii=False, indent=2)}")
    if e.get("stdout"):
        print(f"\n── 标准输出 ──\n{e['stdout']}")
    if e.get("output"):
        print(f"\n── result 变量 ──\n{json.dumps(e['output'], ensure_ascii=False, indent=2)}")
    if e.get("error"):
        print(f"\n── 错误 ──\n{e['error']}")


# ── 参数解析 ────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="数据收集服务 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--url", help=f"API 服务地址")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # setup（首次使用初始化，交互式保存凭证）
    sub.add_parser("setup", help="首次使用初始化：保存登录凭证到本地，后续 Token 自动续期")

    # check-auth（检查 token，过期时自动用保存的凭证续期）
    sub.add_parser("check-auth", help="检查当前登录状态（Token 过期时自动续期）")

    # login（手动重新登录，同时更新保存的凭证）
    p_login = sub.add_parser("login", help="手动登录（同时更新本地凭证）")
    p_login.add_argument("-u", "--username", help="用户名")
    p_login.add_argument("-p", "--password", help="密码")

    # articles
    p_art = sub.add_parser("articles", help="文章管理")
    art_sub = p_art.add_subparsers(dest="subcommand", metavar="<subcommand>")

    p_art_list = art_sub.add_parser("list", help="列出文章（服务端分页，默认每页50条）")
    p_art_list.add_argument("--source", type=int, help="按订阅源 ID 过滤")
    p_art_list.add_argument("--limit", type=int, default=50, help="每页条数（默认 50）")
    p_art_list.add_argument("--search", help="按标题关键词搜索")
    p_art_list.add_argument("--date-from", dest="date_from", metavar="YYYY-MM-DD", help="发布时间起始日期")
    p_art_list.add_argument("--date-to", dest="date_to", metavar="YYYY-MM-DD", help="发布时间截止日期")

    p_art_dl = art_sub.add_parser("download", help="下载单篇文章")
    p_art_dl.add_argument("id", type=int, help="文章 ID")

    p_art_batch = art_sub.add_parser("batch-download", help="批量下载文章为 ZIP")
    p_art_batch.add_argument("ids", help="文章 ID 列表，逗号分隔，如 1,2,3")
    p_art_batch.add_argument("-o", "--output", help="输出文件路径（默认 articles.zip）")
    p_art_batch.add_argument("-t", "--type", choices=["pdf", "md"], default="md",
                              help="下载类型：pdf（仅 PDF）或 md（Markdown + 图片，默认）")

    # subscriptions
    p_sub = sub.add_parser("subscriptions", help="订阅源管理")
    sub_sub = p_sub.add_subparsers(dest="subcommand", metavar="<subcommand>")

    sub_sub.add_parser("list", help="列出订阅源")

    p_sub_add = sub_sub.add_parser("add", help="添加新订阅源（交互式引导）")
    p_sub_add.add_argument("--name", help="公众号名称（需与文章作者名完全一致）")
    p_sub_add.add_argument("--url", dest="article_url", help="该公众号的任意一篇文章地址")
    p_sub_add.add_argument("--pdf", action="store_true", default=None, help="开启 PDF 解析")
    p_sub_add.add_argument("--no-pdf", dest="no_pdf", action="store_true", default=None, help="关闭 PDF 解析")
    p_sub_add.add_argument("--check-time", dest="check_time", metavar="DATETIME",
                           help="首次检查时间，格式 YYYY-MM-DDTHH:MM（仅在 --frequency 非 none 时生效；省略则默认当前时间+5分钟）")
    p_sub_add.add_argument("--frequency", metavar="FREQ",
                           help="更新频率：none / 12h / 1d / 2d / 7d（不指定则交互选择）")

    p_sub_check = sub_sub.add_parser("check", help="手动检查更新")
    p_sub_check.add_argument("id", type=int, help="订阅源 ID")

    # hooks
    p_hook = sub.add_parser("hooks", help="Hook 管理")
    hook_sub = p_hook.add_subparsers(dest="subcommand", metavar="<subcommand>")

    p_hook_list = hook_sub.add_parser("list", help="列出 Hook")
    p_hook_list.add_argument("source_id", type=int, help="订阅源 ID")

    p_hook_create = hook_sub.add_parser("create", help="创建新 Hook")
    p_hook_create.add_argument("source_id", type=int, help="订阅源 ID")
    p_hook_create.add_argument("--name", required=True, help="Hook 名称")
    p_hook_create.add_argument("--hook-type", choices=["full", "judge_only"], default="full",
                               help="Hook 类型：full（判断+操作，默认）/ judge_only（仅判断，无结果文件）")
    p_hook_create.add_argument("--judgment-prompt", required=True, metavar="PROMPT",
                               help="判断 Prompt（正文或 @文件路径，@- 从 stdin 读取）")
    p_hook_create.add_argument("--action-prompt", default=None, metavar="PROMPT",
                               help="操作 Prompt（full 类型必填；judge_only 类型留空）（正文或 @文件路径）")
    p_hook_create.add_argument("--description", help="描述（可选）")
    p_hook_create.add_argument("--disabled", action="store_true", help="创建时设为禁用状态")

    p_hook_update = hook_sub.add_parser("update", help="更新 Hook 配置（只更新提供的字段）")
    p_hook_update.add_argument("source_id", type=int, help="订阅源 ID")
    p_hook_update.add_argument("hook_id", type=int, help="Hook ID")
    p_hook_update.add_argument("--name", help="新名称")
    p_hook_update.add_argument("--description", help="新描述")
    p_hook_update.add_argument("--judgment-prompt", metavar="PROMPT",
                               help="新判断 Prompt（正文或 @文件路径）")
    p_hook_update.add_argument("--action-prompt", metavar="PROMPT",
                               help="新操作 Prompt（正文或 @文件路径）")
    g_active = p_hook_update.add_mutually_exclusive_group()
    g_active.add_argument("--enable", action="store_true", help="启用此 Hook")
    g_active.add_argument("--disable", action="store_true", help="禁用此 Hook")

    p_hook_trigger = hook_sub.add_parser("trigger", help="对所有已解析文章重新触发某 Hook（清除旧结果）")
    p_hook_trigger.add_argument("source_id", type=int, help="订阅源 ID")
    p_hook_trigger.add_argument("hook_id", type=int, help="Hook ID")

    p_hook_retry = hook_sub.add_parser("retry", help="对单篇文章重新触发某 Hook（清除旧结果）")
    p_hook_retry.add_argument("article_id", type=int, help="文章 ID")
    p_hook_retry.add_argument("hook_id", type=int, help="Hook ID")

    p_hook_res = hook_sub.add_parser("results", help="获取 Hook 执行结果")
    p_hook_res.add_argument("source_id", type=int, help="订阅源 ID")
    p_hook_res.add_argument("hook_id", type=int, help="Hook ID")
    p_hook_res.add_argument("-o", "--output", help="导出 CSV 文件路径")

    # metrics
    p_met = sub.add_parser("metrics", help="指标监控")
    met_sub = p_met.add_subparsers(dest="subcommand", metavar="<subcommand>")

    met_sub.add_parser("list", help="列出指标及最新值")

    p_met_run = met_sub.add_parser("run", help="手动触发爬取")
    p_met_run.add_argument("id", type=int, help="指标 ID")

    p_met_data = met_sub.add_parser("data", help="获取指标全部历史数据（时序，可导出 CSV）")
    p_met_data.add_argument("id", type=int, help="指标 ID")
    p_met_data.add_argument("-o", "--output", help="导出 CSV 文件路径（含 UTF-8 BOM，可直接用 Excel 打开）")

    p_met_create = met_sub.add_parser("create", help="新建指标（仅 root 组，创建前自动验证代码）")
    p_met_create.add_argument("--name",        required=True,  help="指标名称")
    p_met_create.add_argument("--code",        required=True,  help="爬虫代码字符串或 @文件路径（如 @crawler.py）")
    p_met_create.add_argument("--pk-col",      required=True,  dest="pk_col",   help="主键列名（如 date）")
    p_met_create.add_argument("--val-col",     required=True,  dest="val_col",  help="主要值列名（如 value）")
    p_met_create.add_argument("--sort-col",    required=True,  dest="sort_col", help="排序列名（通常与主键列相同）")
    p_met_create.add_argument("--unit",        default=None,   help="单位（如 元/吨）")
    p_met_create.add_argument("--description", default=None,   help="描述")
    p_met_create.add_argument("--frequency",   default="1d",   help="爬取频率：none/12h/1d/2d/7d（默认 1d）")
    p_met_create.add_argument("--check-time",  default=None,   dest="check_time", help="首次爬取时间 YYYY-MM-DDTHH:MM")
    p_met_create.add_argument("--metric-group-id", default=None, type=int, dest="metric_group_id",
                               help="所属指标组 ID（不填则放入默认组「未分组」；用 Web UI「管理指标组」查看可用 ID）")

    p_met_update = met_sub.add_parser("update", help="更新指标（仅 root 组，只更新提供的字段）")
    p_met_update.add_argument("id", type=int, help="指标 ID")
    p_met_update.add_argument("--name",        default=None,  help="新名称")
    p_met_update.add_argument("--code",        default=None,  help="新爬虫代码或 @文件路径")
    p_met_update.add_argument("--pk-col",      default=None,  dest="pk_col",   help="新主键列名")
    p_met_update.add_argument("--val-col",     default=None,  dest="val_col",  help="新主要值列名")
    p_met_update.add_argument("--sort-col",    default=None,  dest="sort_col", help="新排序列名")
    p_met_update.add_argument("--unit",        default=None,  help="新单位")
    p_met_update.add_argument("--description", default=None,  help="新描述")
    p_met_update.add_argument("--frequency",   default=None,  help="新爬取频率")
    p_met_update.add_argument("--check-time",  default=None,  dest="check_time", help="新下次爬取时间 YYYY-MM-DDTHH:MM")
    p_met_update.add_argument("--metric-group-id", default=None, type=int, dest="metric_group_id",
                               help="移动到新指标组 ID（用 Web UI「管理指标组」查看可用 ID）")

    p_met_del = met_sub.add_parser("delete", help="删除指标（仅 root 组）")
    p_met_del.add_argument("id", type=int, help="指标 ID")

    p_met_cfg = met_sub.add_parser("config", help="查看全局爬虫配置（仅 root 组）")
    p_met_cfg.add_argument("-o", "--output", default=None, help="导出到 JSON 文件")

    p_met_cfg_set = met_sub.add_parser("config-set", help="整体替换全局爬虫配置（仅 root 组）")
    p_met_cfg_set.add_argument("json_value", help="JSON 字符串或 @文件路径（如 @config.json）")

    p_met_cfg_upd = met_sub.add_parser("config-update", help="合并更新全局配置中的单个/多个键（仅 root 组）")
    p_met_cfg_upd.add_argument("set", nargs="+", metavar="key=value", help="键值对，如 ceci_token=abc api_key=xyz")

    # notices
    p_not = sub.add_parser("notices", help="通知公告")
    not_sub = p_not.add_subparsers(dest="subcommand", metavar="<subcommand>")

    not_sub.add_parser("list", help="列出通知源")

    p_not_files = not_sub.add_parser("files", help="列出某通知源下的公告文件")
    p_not_files.add_argument("source_id", type=int, help="通知源 ID")
    p_not_files.add_argument("--limit", type=int, default=50, help="每页条数（默认 50）")
    p_not_files.add_argument("--search", metavar="KEYWORD", help="按标题关键词筛选")

    p_not_get = not_sub.add_parser("get", help="下载某条公告 PDF 到本地")
    p_not_get.add_argument("source_id", type=int, help="通知源 ID")
    p_not_get.add_argument("file_id", type=int, help="文件 ID（从 notices files 中获取）")
    p_not_get.add_argument("-o", "--output", help="输出路径（默认以标题命名的 .pdf 文件）")

    p_not_crawl = not_sub.add_parser("crawl", help="手动触发爬取（后台异步）")
    p_not_crawl.add_argument("id", type=int, help="通知源 ID")

    # triggers
    p_trig = sub.add_parser("triggers", help="触发器管理（自动化代码执行）")
    trig_sub = p_trig.add_subparsers(dest="subcommand", metavar="<subcommand>")

    trig_sub.add_parser("list", help="列出可访问的触发器")

    p_trig_get = trig_sub.add_parser("get", help="查看触发器详情（含代码）")
    p_trig_get.add_argument("id", type=int, help="触发器 ID")

    p_trig_create = trig_sub.add_parser("create", help="创建触发器")
    p_trig_create.add_argument("--name", required=True, help="触发器名称")
    p_trig_create.add_argument("--event-type", required=True, dest="event_type",
                               help="事件类型（article.new / hook.judged / metric.run / metric.has_update / ...）")
    p_trig_create.add_argument("--code", required=True,
                               help="Python 代码（字符串）或 @文件路径（如 @trigger.py）")
    p_trig_create.add_argument("--description", default=None, help="触发器描述")
    p_trig_create.add_argument("--timeout", type=int, default=60, help="超时秒数（默认 60）")
    p_trig_create.add_argument("--source-id", type=int, default=None, dest="source_id", help="订阅源 ID 过滤")
    p_trig_create.add_argument("--hook-id", type=int, default=None, dest="hook_id", help="Hook ID 过滤")
    p_trig_create.add_argument("--metric-id", type=int, default=None, dest="metric_id", help="指标 ID 过滤")
    p_trig_create.add_argument("--notice-source-id", type=int, default=None, dest="notice_source_id", help="通知源 ID 过滤")
    p_trig_create.add_argument("--disabled", action="store_true", help="创建为禁用状态")

    p_trig_update = trig_sub.add_parser("update", help="更新触发器（只更新提供的字段）")
    p_trig_update.add_argument("id", type=int, help="触发器 ID")
    p_trig_update.add_argument("--name", default=None, help="新名称")
    p_trig_update.add_argument("--description", default=None, help="新描述")
    p_trig_update.add_argument("--event-type", default=None, dest="event_type", help="新事件类型")
    p_trig_update.add_argument("--code", default=None, help="新代码或 @文件路径")
    p_trig_update.add_argument("--timeout", type=int, default=None, help="新超时秒数")
    p_trig_update.add_argument("--source-id", type=int, default=None, dest="source_id", help="新订阅源 ID（-1 清除）")
    p_trig_update.add_argument("--hook-id", type=int, default=None, dest="hook_id", help="新 Hook ID（-1 清除）")
    p_trig_update.add_argument("--metric-id", type=int, default=None, dest="metric_id", help="新指标 ID（-1 清除）")
    p_trig_update.add_argument("--enable", action="store_true", help="启用触发器")
    p_trig_update.add_argument("--disable", action="store_true", help="禁用触发器")

    p_trig_del = trig_sub.add_parser("delete", help="删除触发器及其所有执行记录")
    p_trig_del.add_argument("id", type=int, help="触发器 ID")
    p_trig_del.add_argument("-y", "--yes", action="store_true", help="跳过确认提示")

    p_trig_execs = trig_sub.add_parser("executions", help="列出触发器的执行历史")
    p_trig_execs.add_argument("id", type=int, help="触发器 ID")
    p_trig_execs.add_argument("--limit", type=int, default=20, help="返回条数（默认 20）")

    p_trig_exec = trig_sub.add_parser("execution", help="查看单次执行详情（含输出/错误）")
    p_trig_exec.add_argument("exec_id", type=int, help="执行记录 ID")

    return parser


COMMANDS = {
    ("setup", None): cmd_setup,
    ("check-auth", None): cmd_check_auth,
    ("login", None): cmd_login,
    ("articles", "list"): cmd_articles_list,
    ("articles", "download"): cmd_articles_download,
    ("articles", "batch-download"): cmd_articles_batch_download,
    ("subscriptions", "list"): cmd_subscriptions_list,
    ("subscriptions", "add"): cmd_subscriptions_add,
    ("subscriptions", "check"): cmd_subscriptions_check,
    ("hooks", "list"): cmd_hooks_list,
    ("hooks", "create"): cmd_hooks_create,
    ("hooks", "update"): cmd_hooks_update,
    ("hooks", "trigger"): cmd_hooks_trigger,
    ("hooks", "retry"): cmd_hooks_retry,
    ("hooks", "results"): cmd_hooks_results,
    ("metrics", "list"):          cmd_metrics_list,
    ("metrics", "run"):           cmd_metrics_run,
    ("metrics", "data"):          cmd_metrics_data,
    ("metrics", "create"):        cmd_metrics_create,
    ("metrics", "update"):        cmd_metrics_update,
    ("metrics", "delete"):        cmd_metrics_delete,
    ("metrics", "config"):        cmd_metrics_config_get,
    ("metrics", "config-set"):    cmd_metrics_config_set,
    ("metrics", "config-update"): cmd_metrics_config_update,
    ("notices", "list"):  cmd_notices_list,
    ("notices", "files"): cmd_notices_files,
    ("notices", "get"):   cmd_notices_get,
    ("notices", "crawl"): cmd_notices_crawl,
    ("triggers", "list"):       cmd_triggers_list,
    ("triggers", "get"):        cmd_triggers_get,
    ("triggers", "create"):     cmd_triggers_create,
    ("triggers", "update"):     cmd_triggers_update,
    ("triggers", "delete"):     cmd_triggers_delete,
    ("triggers", "executions"): cmd_triggers_executions,
    ("triggers", "execution"):  cmd_triggers_execution,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.url:
        base_url = args.url.rstrip("/")
    else:
        base_url = _fetch_server_url()
        if not base_url:
            print("错误：无法从 Gitee 获取服务器地址，请检查网络连接", file=sys.stderr)
            print("如需临时指定地址，可用 --url 参数，例如：--url http://1.2.3.4:8000", file=sys.stderr)
            sys.exit(1)
    config = {"base_url": base_url}

    command = args.command
    subcommand = getattr(args, "subcommand", None)

    if command is None:
        parser.print_help()
        sys.exit(0)

    key = (command, subcommand) if subcommand else (command, None)
    handler = COMMANDS.get(key)
    if handler is None:
        parser.parse_args([command, "--help"])
        sys.exit(1)

    try:
        handler(args, config)
    except requests.exceptions.ConnectionError:
        print(f"无法连接到服务器: {config['base_url']}", file=sys.stderr)
        print("请确认服务已启动，或用 --url 指定正确的地址", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            print("认证失败（401），请先执行 login 命令重新登录", file=sys.stderr)
        else:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            print(f"请求失败: {detail}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(0)


if __name__ == "__main__":
    main()

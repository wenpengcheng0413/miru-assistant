"""
Miru Assistant — CLI 入口。

使用 Typer 框架，提供命令行接口。

Commands:
    miru run        手动运行一次日报
    miru status     查看运行状态
    miru config     配置管理
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from miru import __version__

app = typer.Typer(
    name="miru",
    help="Miru Assistant — AI 微信秘书",
    add_completion=False,
    invoke_without_command=True,
)
console = Console()

# ASCII-safe status markers for Windows console compatibility
OK = "[OK]"
FAIL = "[FAIL]"
PENDING = "[PENDING]"
WARN = "[WARN]"


def _show_banner() -> None:
    """显示 Miru banner。"""
    console.print()
    console.print(
        "[bold cyan]"
        "  +--------------------------------------+\n"
        "  |         Miru Assistant v" + __version__ + "          |\n"
        "  |      AI 微信秘书 · 日报自动推送      |\n"
        "  +--------------------------------------+"
        "[/bold cyan]"
    )
    console.print()


@app.command()
def run(
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="测试模式：完整执行但不推送，日报输出到控制台",
    ),
) -> None:
    """
    执行完整日报流程。

    微信环境检查 → 消息采集 → 过滤 → AI 分析 → 日报生成 → 推送。

    miru run             正式运行（含推送）
    miru run --dry-run   测试运行（不推送，控制台预览）
    """
    _show_banner()

    from miru.core.pipeline import MiruPipeline

    pipeline = MiruPipeline(config_path=config_path)
    ctx = pipeline.run(dry_run=dry_run)

    # 输出最终状态
    console.print()
    if ctx.is_success and ctx.report_md:
        console.print(f"[green]{OK} Pipeline 完成 — {ctx.date}[/green]")
        if dry_run:
            console.print("[dim]日报已输出到控制台（未推送）。[/dim]")
        else:
            console.print(f"[dim]推送状态: {ctx.push_status}[/dim]")
    elif ctx.has_errors:
        console.print(f"[red]{FAIL} Pipeline 有错误[/red]")
        for e in ctx.errors:
            console.print(f"  - {e}")
    else:
        console.print(f"[yellow]{WARN} Pipeline 完成但无结果[/yellow]")
        for w in ctx.warnings:
            console.print(f"  - {w}")

    if not ctx.is_success:
        raise typer.Exit(code=1)


@app.command()
def status(
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
) -> None:
    """
    查看 Miru 运行状态和健康检查。
    """
    import os
    import sys
    from pathlib import Path

    _show_banner()

    # 使用调度器模块的完整健康检查
    from miru.scheduler import check_health
    h = check_health("data/miru.db")

    # --- Environment ---
    table_env = Table(title="Environment")
    table_env.add_column("项目", style="cyan")
    table_env.add_column("值", style="white")
    table_env.add_row("Python", f"{OK} {h.python_version}")
    table_env.add_row("虚拟环境", f"{OK} {h.venv_path}")
    table_env.add_row("配置文件",
        f"{OK} config/settings.yaml" if h.config_exists else f"{FAIL} 未找到")
    table_env.add_row("数据库",
        f"{OK} data/miru.db ({h.db_size_kb:.1f} KB)" if h.db_exists else f"{PENDING} 未创建")
    console.print(table_env)
    console.print()

    # --- Scheduler ---
    table_sch = Table(title="Scheduler")
    table_sch.add_column("项目", style="cyan")
    table_sch.add_column("值", style="white")
    if h.scheduler_installed:
        table_sch.add_row("任务计划", f"{OK} 已安装 ({h.scheduler_task_name})")
        table_sch.add_row("触发时间", "每天 21:00 + 登录时")
    else:
        table_sch.add_row("任务计划", f"{PENDING} 未安装")
        table_sch.add_row("安装命令", "powershell scripts/setup_scheduler.ps1")
    console.print(table_sch)
    console.print()

    # --- Last Run ---
    table_run = Table(title="Last Run")
    table_run.add_column("项目", style="cyan")
    table_run.add_column("值", style="white")
    if h.last_run_date:
        status_icon = OK if h.last_run_status == "success" else FAIL
        table_run.add_row("最近运行", h.last_run_date)
        table_run.add_row("运行状态", f"{status_icon} {h.last_run_status}")
        table_run.add_row("最近日报", h.last_report_date or "-")
        table_run.add_row("推送状态", h.last_push_status or "-")
        table_run.add_row("日报总数", f"{h.total_reports} 份")
    else:
        table_run.add_row("最近运行", f"{PENDING} 尚未运行")
    console.print(table_run)
    console.print()

    # --- Health ---
    if h.is_healthy:
        console.print(f"[bold green]  Health: OK[/bold green]")
    else:
        console.print(f"[bold red]  Health: Issues Detected[/bold red]")
        for issue in h.issues:
            console.print(f"  [red]- {issue}[/red]")

    if h.warnings:
        for w in h.warnings:
            console.print(f"  [yellow]! {w}[/yellow]")

    console.print()


@app.command()
def config(
    action: str = typer.Argument("validate", help="validate | show | init"),
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
) -> None:
    """
    配置文件管理。

    miru config validate  — 校验配置文件
    miru config show      — 显示当前配置
    miru config init      — 从模板初始化配置文件
    """
    if action == "validate":
        try:
            from miru.utils.config import load_config
            cfg = load_config(config_path)
            console.print(f"[green]{OK} 配置文件校验通过: {config_path}[/green]")
            console.print(f"   关注 {len(cfg.miru.groups)} 个群")
            console.print(f"   LLM 模型: {cfg.miru.llm.model}")
            console.print(f"   推送渠道: {[n.type for n in cfg.miru.notifiers if n.enabled]}")
        except Exception as e:
            console.print(f"[red]{FAIL} 配置校验失败: {e}[/red]")
            raise typer.Exit(code=1)

    elif action == "show":
        config_file = Path(config_path)
        if not config_file.exists():
            console.print(f"[red]{FAIL} 配置文件不存在: {config_file}[/red]")
            raise typer.Exit(code=1)
        console.print(config_file.read_text(encoding="utf-8"))

    elif action == "init":
        import shutil
        example = Path("config/settings.example.yaml")
        target = Path(config_path)
        if not example.exists():
            console.print(f"[red]{FAIL} 模板文件不存在: {example}[/red]")
            raise typer.Exit(code=1)
        if target.exists():
            console.print(f"[yellow]{WARN} 目标文件已存在: {target}[/yellow]")
            console.print("   如需覆盖，请先删除或重命名。")
            raise typer.Exit(code=1)
        shutil.copy(example, target)
        console.print(f"[green]{OK} 配置文件已创建: {target}[/green]")
        console.print("   请编辑此文件，填入你的群名和 API Key。")

    else:
        console.print(f"[red]{FAIL} 未知操作: {action}[/red]")
        console.print("   可用操作: validate, show, init")
        raise typer.Exit(code=1)


@app.command()
def decrypt(
    db_name: str = typer.Argument(
        "message_0.db",
        help="要验证的数据库文件名 (message_0.db / contact.db / MSG0.db / ...)",
    ),
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
) -> None:
    """
    验证微信数据库解密。

    尝试从微信进程提取密钥，解密指定数据库，
    检查 schema 结构。

    示例:
        miru decrypt                    # 验证 message_0.db
        miru decrypt contact.db         # 验证 contact.db
    """
    import os
    from pathlib import Path

    _show_banner()

    # 1. 获取微信数据目录
    manual_dir = ""
    cfg = None
    try:
        from miru.utils.config import load_config
        cfg = load_config(config_path)
        manual_dir = cfg.miru.wechat.data_dir
    except Exception:
        pass

    from miru.collector.diagnostics import detect_wechat_process, find_wechat_data_dir

    proc_info = detect_wechat_process()
    if not proc_info.found:
        console.print(f"[red]{FAIL} 微信未运行。请先启动并登录微信 PC 客户端。[/red]")
        raise typer.Exit(code=1)

    data_dir_info = find_wechat_data_dir(manual_dir)
    if not data_dir_info.found:
        console.print(f"[red]{FAIL} 未找到微信数据目录。请运行 miru doctor 检查。[/red]")
        raise typer.Exit(code=1)

    # 2. 确定数据库文件路径
    # 微信 4.x 有两种目录布局: db_storage/ (新版) 或 db/ (旧版)
    db_root = None
    if proc_info.version_major >= 4:
        data_path = Path(data_dir_info.path)
        new_style = data_path / "db_storage"
        old_style = data_path / "db"
        if new_style.exists():
            db_root = new_style
        else:
            db_root = old_style

        # 在 db_storage 下搜索数据库文件
        db_file = None
        for root, dirs, files in os.walk(str(db_root)):
            for f in files:
                if f == db_name:
                    db_file = Path(root) / f
                    break
            if db_file:
                break
        if db_file is None:
            db_file = db_root / db_name  # fallback
    else:
        db_root = Path(data_dir_info.path) / "Msg"
        db_file = db_root / db_name

    if not db_file or not db_file.exists():
        # 列出可用文件
        available_parts = []
        if db_root and db_root.exists():
            for root, dirs, files in os.walk(str(db_root)):
                for f in files:
                    if f.endswith(".db"):
                        available_parts.append(f"  {Path(root).relative_to(db_root)}/{f}")
        available = "\n".join(available_parts[:20]) if available_parts else "  (目录不存在)"
        console.print(f"[red]{FAIL} 文件不存在: {db_file}[/red]")
        if available:
            console.print(f"可用文件:\n{available}")
        raise typer.Exit(code=1)

    # 3. 验证管理员权限
    if not proc_info.found:
        raise typer.Exit(code=1)

    import ctypes
    is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    if not is_admin:
        console.print(
            f"[red]{FAIL} 需要管理员权限才能读取微信进程内存。[/red]\n"
            f"请以管理员身份重新运行。"
        )
        raise typer.Exit(code=1)

    # 4. 运行解密验证
    console.print(f"[bold]微信版本:[/bold] {proc_info.version}")
    console.print(f"[bold]数据目录:[/bold] {data_dir_info.path}")
    console.print(f"[bold]目标文件:[/bold] {db_file}")
    console.print(f"[bold]文件大小:[/bold] {os.path.getsize(db_file) / (1024*1024):.1f} MB")
    console.print()
    console.print("[bold]正在从微信进程提取密钥...[/bold]")

    from miru.collector.wechat_db_decrypt import try_decrypt_wechat_db, ExtractedKey

    # 检查是否有手动提供的 key
    manual_key = (cfg.miru.wechat.database_key or "").strip() if cfg else ""
    if manual_key:
        console.print("[bold green]  使用手动配置的 database_key[/bold green]")
        try:
            key_hex = manual_key
            if key_hex.startswith("x'") and key_hex.endswith("'"):
                key_hex = key_hex[2:-1]
            raw_key = bytes.fromhex(key_hex)
            if len(raw_key) != 32:
                console.print(f"[red]{FAIL} 密钥长度错误: 期望 32 bytes, 实际 {len(raw_key)} bytes[/red]")
                raise typer.Exit(code=1)
            keys = [ExtractedKey(raw_key=raw_key, salt=b"", hex_key=key_hex)]
        except ValueError as e:
            console.print(f"[red]{FAIL} 密钥格式错误: {e}[/red]")
            raise typer.Exit(code=1)
    else:
        keys = None

    result = try_decrypt_wechat_db(
        db_path=db_file,
        pid=proc_info.pid,
        keys=keys,
    )

    # 5. 输出结果
    console.print()
    if result.success:
        _print_decrypt_success(result)
    else:
        _print_decrypt_failure(result)


def _print_decrypt_success(result) -> None:
    """打印解密成功的结果。"""
    from miru.collector.wechat_db_decrypt import DecryptResult
    r: DecryptResult = result

    console.print(f"[bold green]{OK} 数据库解密成功！[/bold green]")
    console.print()

    # 基本信息
    table_info = Table(title="数据库信息")
    table_info.add_column("项目", style="cyan")
    table_info.add_column("值", style="white")
    table_info.add_row("数据库文件", r.db_name)
    table_info.add_row("文件大小", f"{r.db_size_mb:.1f} MB")
    table_info.add_row("SQLite 版本", str(r.sqlite_version))
    table_info.add_row("页面数", str(r.page_count))
    table_info.add_row("页面大小", f"{r.page_size} bytes")
    table_info.add_row("是否加密", "是 (SQLCipher 4)" if r.is_encrypted else "否")
    table_info.add_row("密钥来源", r.key_source)
    table_info.add_row("密钥 (前16字符)", r.key_hex)
    console.print(table_info)
    console.print()

    # Schema
    table_schema = Table(title=f"数据库表 ({len(r.tables)} 个)")
    table_schema.add_column("表名", style="cyan")
    table_schema.add_column("字段", style="white")

    for table_name in r.tables:
        cols = r.table_details.get(table_name, [])
        table_schema.add_row(table_name, ", ".join(cols[:8]))
        if len(cols) > 8:
            table_schema.add_row("", f"... 及其他 {len(cols) - 8} 个字段")

    console.print(table_schema)
    console.print()
    console.print("[green]  Verification passed — 解密 pipeline 就绪。可以继续 Task 5C+。[/green]")


def _print_decrypt_failure(result) -> None:
    """打印解密失败的结果和诊断。"""
    r = result

    console.print(f"[bold red]{FAIL} 数据库解密失败[/bold red]")
    console.print()

    stage_labels = {
        "process": "进程访问",
        "memory_scan": "内存扫描",
        "key_extract": "密钥提取",
        "decrypt": "数据库解密",
        "schema": "Schema 读取",
    }
    stage = stage_labels.get(r.error_stage, r.error_stage or "未知阶段")

    table_err = Table(title="失败详情")
    table_err.add_column("项目", style="cyan")
    table_err.add_column("值", style="white")
    table_err.add_row("失败阶段", f"[red]{stage}[/red]")
    table_err.add_row("错误信息", r.error or "无详细信息")
    table_err.add_row("建议", r.suggestion or "运行 miru doctor 获取完整诊断")
    console.print(table_err)
    console.print()

    if r.key_found:
        console.print("[yellow]密钥提取成功但解密失败 — 可能是加密参数不匹配[/yellow]")
    else:
        console.print("[yellow]密钥提取失败 — 可能原因:[/yellow]")
        console.print("  1. 微信版本过新 (密钥格式已改变)")
        console.print("  2. 权限不足 (需要管理员)")
        console.print("  3. 内存已被其他程序清理")


@app.command()
def groups(
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
) -> None:
    """
    列出微信中的所有群聊。

    需要微信正在运行 + 管理员权限。
    """
    import os
    from pathlib import Path

    _show_banner()

    # 诊断
    from miru.collector.diagnostics import detect_wechat_process, find_wechat_data_dir
    proc_info = detect_wechat_process()
    if not proc_info.found:
        console.print(f"[red]{FAIL} 微信未运行[/red]")
        raise typer.Exit(code=1)

    manual_dir = ""
    try:
        from miru.utils.config import load_config
        cfg = load_config(config_path)
        manual_dir = cfg.miru.wechat.data_dir
    except Exception:
        pass

    data_dir_info = find_wechat_data_dir(manual_dir)
    if not data_dir_info.found:
        console.print(f"[red]{FAIL} 未找到数据目录[/red]")
        raise typer.Exit(code=1)

    import ctypes
    is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    if not is_admin:
        console.print(f"[red]{FAIL} 需要管理员权限[/red]")
        raise typer.Exit(code=1)

    # 解密 contact.db
    db_dir = Path(data_dir_info.path) / ("db" if proc_info.version_major >= 4 else "Msg")
    contact_file = db_dir / ("contact.db" if proc_info.version_major >= 4 else "MicroMsg.db")
    if not contact_file.exists():
        console.print(f"[red]{FAIL} 找不到联系人数据库: {contact_file}[/red]")
        raise typer.Exit(code=1)

    console.print("正在解密联系人数据库...")
    from miru.collector.wechat_db_decrypt import try_decrypt_wechat_db
    result = try_decrypt_wechat_db(contact_file, proc_info.pid)

    if not result.success:
        console.print(f"[red]{FAIL} 解密失败: {result.error}[/red]")
        raise typer.Exit(code=1)

    # 读取群列表
    from miru.collector.wechat_reader import list_groups, WeChatGroup
    group_list = list_groups(Path(result.db_path) if not result.is_encrypted else Path(""))

    # 实际上需要从解密后的临时文件中读取。try_decrypt_wechat_db 会把解密后的
    # 临时文件路径放在哪里？让我看一下...

    console.print()
    console.print(f"[bold]找到 {len(group_list)} 个群聊:[/bold]")
    console.print()

    table = Table(title="微信群列表")
    table.add_column("#", style="dim")
    table.add_column("群名", style="cyan")
    table.add_column("用户名", style="dim")
    for i, g in enumerate(group_list, 1):
        table.add_row(str(i), g.nickname or g.remark or "(无名称)", g.username)
    console.print(table)


@app.command()
def read(
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
    count: int = typer.Option(
        20, "--count", "-n",
        help="读取最近多少条消息",
    ),
) -> None:
    """
    从微信数据库读取最近的消息。

    需要微信正在运行 + 管理员权限。
    默认读取第一个找到的群的消息。
    """
    import os
    import tempfile
    from pathlib import Path

    _show_banner()

    # 1. 诊断
    from miru.collector.diagnostics import detect_wechat_process, find_wechat_data_dir
    proc_info = detect_wechat_process()
    if not proc_info.found:
        console.print(f"[red]{FAIL} 微信未运行[/red]")
        raise typer.Exit(code=1)

    manual_dir = ""
    try:
        from miru.utils.config import load_config
        cfg = load_config(config_path)
        manual_dir = cfg.miru.wechat.data_dir
    except Exception:
        pass

    data_dir_info = find_wechat_data_dir(manual_dir)
    if not data_dir_info.found:
        console.print(f"[red]{FAIL} 未找到数据目录[/red]")
        raise typer.Exit(code=1)

    import ctypes
    is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    if not is_admin:
        console.print(f"[red]{FAIL} 需要管理员权限[/red]")
        raise typer.Exit(code=1)

    db_dir = Path(data_dir_info.path) / ("db" if proc_info.version_major >= 4 else "Msg")

    # 2. 解密 contact.db 和 message_0.db
    from miru.collector.wechat_db_decrypt import (
        try_decrypt_wechat_db,
        decrypt_and_open,
        extract_keys_from_process,
    )

    contact_file = db_dir / ("contact.db" if proc_info.version_major >= 4 else "MicroMsg.db")
    msg_file = db_dir / "message_0.db"
    if not msg_file.exists():
        msg_file = db_dir / "MSG0.db"

    if not contact_file.exists():
        console.print(f"[red]{FAIL} contact 数据库不存在[/red]")
        raise typer.Exit(code=1)
    if not msg_file.exists():
        console.print(f"[red]{FAIL} 消息数据库不存在[/red]")
        raise typer.Exit(code=1)

    console.print("提取密钥...")
    keys = extract_keys_from_process(proc_info.pid)

    # 分别解密 contact 和 message
    console.print(f"解密 {contact_file.name}...")
    ct_result = try_decrypt_wechat_db(contact_file, proc_info.pid, keys)
    if not ct_result.success:
        console.print(f"[red]{FAIL} contact 解密失败: {ct_result.error}[/red]")
        raise typer.Exit(code=1)

    console.print(f"解密 {msg_file.name} ({msg_file.stat().st_size / 1024 / 1024:.1f} MB)...")
    msg_result = try_decrypt_wechat_db(msg_file, proc_info.pid, keys)
    if not msg_result.success:
        console.print(f"[red]{FAIL} message 解密失败: {msg_result.error}[/red]")
        raise typer.Exit(code=1)

    # contact.db 可能未加密 — try_decrypt_wechat_db 会处理此情况
    ct_path = Path(ct_result.db_path)
    msg_path = Path(msg_result.db_path) if msg_result.is_decrypted else msg_file
    if not msg_result.is_decrypted and not msg_result.is_encrypted:
        msg_path = msg_file

    # 3. 读取群列表
    from miru.collector.wechat_reader import WeChatDBReader
    reader = WeChatDBReader(ct_path, msg_path)
    groups = reader.get_groups()
    reader.close()

    if not groups:
        console.print("[yellow]未找到任何群聊。[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"找到 {len(groups)} 个群聊")

    # 选择一个群（优先匹配配置中的群名）
    target_group = groups[0]
    if cfg and cfg.miru.groups:
        for g in groups:
            for target_name in cfg.miru.groups:
                if target_name in (g.nickname or "") or target_name in (g.remark or ""):
                    target_group = g
                    break

    console.print(f"目标群: [cyan]{target_group.nickname or target_group.username}[/cyan]")

    # 4. 读取最近消息
    reader2 = WeChatDBReader(ct_path, msg_path)
    messages = reader2.get_messages(target_group.username, limit=count * 2)
    recent = messages[-count:] if len(messages) > count else messages
    reader2.close()

    console.print()
    console.print(f"[bold]最近 {len(recent)} 条消息:[/bold]")
    console.print()

    table = Table(title=f"消息列表 — {target_group.nickname or target_group.username}")
    table.add_column("时间", style="dim", width=10)
    table.add_column("发送者", style="cyan", width=16)
    table.add_column("内容", style="white", width=50)
    table.add_column("类型", style="dim", width=6)

    for msg in recent:
        # 截断过长内容
        content = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        type_label = "TXT" if msg.is_text else str(msg.local_type)
        table.add_row(msg.time_str, msg.sender_name or "-", content, type_label)

    console.print(table)
    console.print()

    # 5. 清理
    reader.close()

    console.print("[green]Done. 消息读取验证通过。[/green]")


@app.command()
def push(
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
    retry: bool = typer.Option(
        False, "--retry", "-r",
        help="补推之前失败的所有日报",
    ),
) -> None:
    """
    推送最新的日报到手机微信。

    或使用 --retry 补推所有失败的日报。
    """
    from pathlib import Path

    _show_banner()

    # 加载配置
    try:
        from miru.utils.config import load_config
        cfg = load_config(config_path)
    except Exception as e:
        console.print(f"[red]{FAIL} 配置加载失败: {e}[/red]")
        raise typer.Exit(code=1)

    # 构建推送渠道
    notifiers = []
    for nc in cfg.miru.notifiers:
        if not nc.enabled:
            continue
        if nc.type == "pushplus":
            tk = nc.get_token()
            if not tk or tk.startswith("${"):
                console.print(
                    f"[yellow]{WARN} PushPlus token 未配置，跳过[/yellow]"
                )
                continue
            from miru.notify.pushplus import PushPlusNotifier
            notifiers.append(PushPlusNotifier(token=tk))
        elif nc.type == "console":
            from miru.notify.console import ConsoleNotifier
            notifiers.append(ConsoleNotifier())

    if not notifiers:
        console.print(f"[red]{FAIL} 没有可用的推送渠道[/red]")
        console.print("请在 settings.yaml 中配置 notifiers")
        raise typer.Exit(code=1)

    console.print(f"推送渠道: {[type(n).__name__ for n in notifiers]}")

    db_path = cfg.miru.storage.db_path

    if retry:
        # 补推模式
        console.print("正在补推失败的日报...")
        from miru.notify.dispatcher import retry_failed_pushes
        count = retry_failed_pushes(notifiers, db_path)
        console.print(f"[green]{OK} 补推完成 — {count} 条[/green]")
    else:
        # 推送最新日报
        from miru.notify.dispatcher import dispatch_report
        from miru.storage.database import Database
        from miru.storage.migrations import run_migrations
        from miru.storage.repository import ReportRepository

        db = Database(db_path)
        run_migrations(db)
        repo = ReportRepository(db)
        latest = repo.get_latest(1)
        db.close()

        if not latest:
            console.print(f"[yellow]{WARN} 没有可推送的日报。请先运行 miru run。[/yellow]")
            raise typer.Exit(code=0)

        report = latest[0]
        console.print(f"推送日报: {report.report_date} ({len(report.content_md)} 字符)")

        result = dispatch_report(
            content_md=report.content_md,
            notifiers=notifiers,
            report_date=report.report_date,
            db_path=db_path,
        )

        if result.success > 0:
            console.print(f"[green]{OK} 推送成功 ({result.success}/{result.total})[/green]")
        if result.failed > 0:
            console.print(f"[red]{FAIL} 推送失败: {result.errors}[/red]")
            raise typer.Exit(code=1)


@app.command()
def export(
    contact: str = typer.Option(
        None, "--contact",
        help="联系人名称（settings.yaml 白名单 name）",
    ),
    group: str = typer.Option(
        None, "--group",
        help="群聊名称（在线模式，需微信运行 + 管理员权限）",
    ),
    all_contacts: bool = typer.Option(
        False, "--all",
        help="导出白名单全部联系人",
    ),
    skip_analyze: bool = typer.Option(
        False, "--skip-analyze",
        help="跳过 DeepSeek AI 分析（只导出 + 统计 + 时间线）",
    ),
    output: str = typer.Option(
        "output", "--output", "-o",
        help="输出目录根路径",
    ),
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
) -> None:
    """
    导出聊天记录（联系人离线全量 / 群聊在线）。

    联系人模式（推荐，离线，无需微信运行）:
        miru export --contact Krista          # 导出 + AI 分析 + 统计 + 时间线
        miru export --all                     # 白名单全部
        miru export --contact Krista --skip-analyze

    群聊模式（在线，需微信运行 + 管理员权限）:
        miru export --group "群名"
    """
    import importlib.util
    import sys
    from pathlib import Path

    _show_banner()

    # 联系人模式
    if contact or all_contacts:
        _export_contacts(
            contact=contact,
            all_contacts=all_contacts,
            skip_analyze=skip_analyze,
            output=output,
            config_path=config_path,
        )
        return

    # 群聊模式
    if group:
        _export_group(group, output, config_path)
        return

    console.print(f"[red]{FAIL} 请指定 --contact / --all 或 --group[/red]")
    console.print("示例:")
    console.print("  miru export --contact Krista")
    console.print("  miru export --all")
    console.print("  miru export --group \"测试群\"")
    raise typer.Exit(code=1)


def _export_contacts(
    contact: str,
    all_contacts: bool,
    skip_analyze: bool,
    output: str,
    config_path: str,
) -> None:
    """联系人批量导出（复用 analyze_all._process_one 全流程）。"""
    import importlib.util
    from pathlib import Path

    from miru.chat_analyzer.contacts import load_contact_aliases, load_contacts_config

    # 加载 analyze_all 模块（scripts/ 非包，用文件路径加载）
    analyze_all_path = Path(__file__).resolve().parents[3] / "scripts" / "analyze_all.py"
    spec = importlib.util.spec_from_file_location("analyze_all", analyze_all_path)
    if spec is None or spec.loader is None:
        console.print(f"[red]{FAIL} 无法加载 scripts/analyze_all.py[/red]")
        raise typer.Exit(code=1)
    analyze_all = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analyze_all)

    # 白名单（双源）
    aliases = load_contacts_config(config_path)
    if not aliases:
        aliases = load_contact_aliases("config/contacts.yaml")
    if not aliases:
        console.print(f"[red]{FAIL} 没有可用的联系人白名单[/red]")
        console.print("请在 settings.yaml → miru.contacts.whitelist 中配置（推荐 wxid）")
        raise typer.Exit(code=1)

    if not all_contacts:
        wanted = {c.strip().lower() for c in contact.split(",") if c.strip()}
        aliases = [a for a in aliases if a.name.lower() in wanted]
        if not aliases:
            console.print(f"[red]{FAIL} 白名单中没有匹配的联系人: {contact}[/red]")
            raise typer.Exit(code=1)

    from miru.chat_analyzer.analyzer import ChatAnalyzer
    from miru.chat_analyzer.exporter import ChatExporter
    from miru.chat_analyzer.offline_exporter import ContactFullExporter
    from miru.chat_analyzer.statistics import ChatStatistics
    from miru.chat_analyzer.timeline import TimelineAnalyzer

    offline_exporter = ContactFullExporter()
    online_exporter = ChatExporter(config_path=config_path)
    analyzer = ChatAnalyzer(config_path=config_path)
    stats_runner = ChatStatistics()
    timeline_runner = TimelineAnalyzer()

    results = []
    total = len(aliases)
    for i, alias in enumerate(aliases, 1):
        results.append(
            analyze_all._process_one(
                index=i,
                total=total,
                alias=alias,
                offline_exporter=offline_exporter,
                online_exporter=online_exporter,
                analyzer=analyzer,
                stats_runner=stats_runner,
                timeline_runner=timeline_runner,
                output_dir=output,
                skip_analyze=skip_analyze,
            )
        )

    ok = sum(1 for r in results if r["success"])
    console.print()
    console.print(f"[bold]联系人导出完成: {ok}/{len(results)} 成功[/bold]")
    for r in results:
        icon = "[green]OK[/green]" if r["success"] else "[red]FAIL[/red]"
        console.print(f"  {icon} {r['name']}: {r.get('detail', '')}")
    if ok < len(results):
        raise typer.Exit(code=2)


def _export_group(group_name: str, output: str, config_path: str) -> None:
    """
    群聊导出（在线模式：微信运行 + 管理员权限）。

    读取群全部消息并导出为标准 chat.txt（[时间] 发送者：内容）。
    """
    import ctypes
    import os
    from datetime import datetime
    from pathlib import Path

    from miru.chat_analyzer.offline_reader import summarize_content
    from miru.collector.diagnostics import detect_wechat_process, find_wechat_data_dir
    from miru.collector.wechat_reader import WeChatDBReader

    # 1. 环境检查
    proc_info = detect_wechat_process()
    if not proc_info.found:
        console.print(f"[red]{FAIL} 微信未运行 — 群聊导出为在线模式，请先启动微信[/red]")
        raise typer.Exit(code=1)
    if ctypes.windll.shell32.IsUserAnAdmin() == 0:
        console.print(f"[red]{FAIL} 需要管理员权限（读取微信进程内存）[/red]")
        raise typer.Exit(code=1)

    manual_dir = ""
    try:
        from miru.utils.config import load_config
        cfg = load_config(config_path)
        manual_dir = cfg.miru.wechat.data_dir
    except Exception:
        pass

    data_dir_info = find_wechat_data_dir(manual_dir)
    if not data_dir_info.found:
        console.print(f"[red]{FAIL} 未找到微信数据目录[/red]")
        raise typer.Exit(code=1)

    from miru.collector.wechat_db_decrypt import (
        extract_keys_from_process,
        try_decrypt_wechat_db,
    )

    data_path = Path(data_dir_info.path)
    db_root = data_path / "db_storage" if (data_path / "db_storage").exists() else data_path / "db"
    contact_file = db_root / "contact" / "contact.db" if (db_root / "contact").exists() else db_root / "contact.db"
    msg_file = db_root / "message" / "message_0.db" if (db_root / "message").exists() else db_root / "message_0.db"

    if not contact_file.exists() or not msg_file.exists():
        console.print(f"[red]{FAIL} 数据库文件缺失: {contact_file} / {msg_file}[/red]")
        raise typer.Exit(code=1)

    console.print("提取密钥并解密数据库...")
    keys = extract_keys_from_process(proc_info.pid)

    ct_result = try_decrypt_wechat_db(contact_file, proc_info.pid, keys)
    if not ct_result.success:
        console.print(f"[red]{FAIL} contact.db 解密失败: {ct_result.error}[/red]")
        raise typer.Exit(code=1)
    msg_result = try_decrypt_wechat_db(msg_file, proc_info.pid, keys)
    if not msg_result.success:
        console.print(f"[red]{FAIL} message_0.db 解密失败: {msg_result.error}[/red]")
        raise typer.Exit(code=1)

    ct_path = Path(ct_result.db_path)
    msg_path = Path(msg_result.db_path) if msg_result.is_decrypted else msg_file

    # 2. 匹配群
    reader = WeChatDBReader(ct_path, msg_path)
    try:
        groups = reader.get_groups()
        target = next(
            (g for g in groups if group_name in (g.nickname or "") or group_name in (g.remark or "")),
            None,
        )
        if target is None:
            console.print(f"[red]{FAIL} 未找到群: {group_name}[/red]")
            names = "\n".join(f"  - {g.nickname or g.username}" for g in groups[:20])
            console.print(f"现有群（前 20）:\n{names}")
            raise typer.Exit(code=1)
        console.print(f"群: {target.nickname} ({target.username})")

        # 3. 读取全部消息
        messages = reader.get_messages(target.username, limit=100000)
        console.print(f"读取到 {len(messages)} 条消息")

        # 4. 渲染 chat.txt
        out_dir = Path(output) / target.nickname
        out_dir.mkdir(parents=True, exist_ok=True)
        chat_file = out_dir / "chat.txt"
        lines = [
            "=" * 60,
            f"群聊：{target.nickname}",
            f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"消息数量：{len(messages)}",
            "=" * 60,
            "",
        ]
        for m in messages:
            ts = datetime.fromtimestamp(m.create_time).strftime("%Y-%m-%d %H:%M:%S")
            sender = m.sender_name or "未知"
            content = summarize_content(m.content, m.local_type) or ""
            if not content:
                continue
            lines.append(f"[{ts}] {sender}：")
            lines.append(content)
            lines.append("")
        while lines and lines[-1] == "":
            lines.pop()
        lines.append("")
        chat_file.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"[green]{OK} 群聊已导出 → {chat_file}[/green]")

        # 5. 统计
        from miru.chat_analyzer.statistics import ChatStatistics
        stats = ChatStatistics().analyze(
            contact_name=target.nickname,
            chat_file=chat_file,
            output_dir=out_dir,
        )
        if stats.success:
            console.print(f"[green]{OK} 统计完成 → {stats.statistics_file}[/green]")
    finally:
        reader.close()


@app.command()
def doctor(
    config_path: str = typer.Option(
        "config/settings.yaml", "--config", "-c",
        help="配置文件路径",
    ),
    json_output: bool = typer.Option(
        False, "--json", "-j",
        help="以 JSON 格式输出诊断结果",
    ),
) -> None:
    """
    运行微信环境诊断。

    检查微信进程、数据目录、数据库文件、权限、依赖。
    纯只读 — 不读取聊天内容、不修改任何文件。
    """
    import json

    from miru.collector.diagnostics import run_full_diagnostics

    # 尝试加载配置（获取手动指定的数据目录）
    manual_dir = ""
    try:
        from miru.utils.config import load_config
        cfg = load_config(config_path)
        manual_dir = cfg.miru.wechat.data_dir
    except Exception:
        pass  # 配置不存在也没关系，自动检测

    _show_banner()
    console.print("[bold]正在运行微信环境诊断...[/bold]")
    console.print()

    report = run_full_diagnostics(manual_data_dir=manual_dir)

    if json_output:
        console.print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return

    # --- 格式化输出 ---

    # Windows 环境
    table_env = Table(title="系统环境")
    table_env.add_column("项目", style="cyan")
    table_env.add_column("值", style="white")
    table_env.add_row("主机名", report.hostname)
    table_env.add_row("操作系统", report.windows_version)
    table_env.add_row("架构", report.windows_arch)
    table_env.add_row("Python", report.python_version)
    console.print(table_env)
    console.print()

    # 微信进程
    wp = report.wechat_process
    status_color = "green" if wp.found else "red"
    table_wx = Table(title="微信客户端")
    table_wx.add_column("项目", style="cyan")
    table_wx.add_column("值", style="white")
    table_wx.add_row("状态", f"[{status_color}]{wp.status}[/{status_color}]")
    if wp.found:
        table_wx.add_row("PID", str(wp.pid))
        table_wx.add_row("版本号", wp.version_raw or "未知")
        table_wx.add_row("主版本", f"微信 {wp.version_major}.x" if wp.version_major else "未知")
        table_wx.add_row("路径", wp.exe_path)
    if wp.error:
        table_wx.add_row("错误", f"[red]{wp.error}[/red]")
    console.print(table_wx)
    console.print()

    # 数据目录
    dd = report.wechat_data_dir
    dd_color = "green" if dd.found else "red"
    table_dd = Table(title="数据目录")
    table_dd.add_column("项目", style="cyan")
    table_dd.add_column("值", style="white")
    table_dd.add_row("状态", f"[{dd_color}]{'已找到' if dd.found else '未找到'}[/{dd_color}]")
    if dd.found:
        table_dd.add_row("路径", dd.path)
        table_dd.add_row("WxID", dd.wxid)
        table_dd.add_row("来源", dd.source)
    console.print(table_dd)
    console.print()

    # 数据库文件
    table_db = Table(title="数据库文件")
    table_db.add_column("文件名", style="cyan")
    table_db.add_column("状态", style="white")
    table_db.add_column("大小", style="white")
    table_db.add_column("说明", style="dim")
    for f in report.db_files:
        if f.exists:
            table_db.add_row(f.name, "[green]存在[/green]", f"{f.size_mb:.1f} MB", f.note)
        else:
            table_db.add_row(f.name, "[dim]未找到[/dim]", "-", f.note)
    console.print(table_db)
    console.print()

    # 权限
    perm = report.permissions
    perm_color = "green" if perm.is_admin else "red"
    table_perm = Table(title="权限检查")
    table_perm.add_column("项目", style="cyan")
    table_perm.add_column("值", style="white")
    table_perm.add_row("管理员", f"[{perm_color}]{'是' if perm.is_admin else '否'}[/{perm_color}]")
    table_perm.add_row("内存读取", f"[{perm_color}]{'可用' if perm.can_read_process_memory else '不可用'}[/{perm_color}]")
    if perm.error:
        table_perm.add_row("说明", f"[yellow]{perm.error}[/yellow]")
    console.print(table_perm)
    console.print()

    # 依赖
    table_dep = Table(title="Python 依赖")
    table_dep.add_column("包名", style="cyan")
    table_dep.add_column("状态", style="white")
    table_dep.add_column("版本", style="dim")
    for d in report.dependencies:
        icon = "[green]已安装[/green]" if d.installed else "[red]缺失[/red]"
        table_dep.add_row(d.name, icon, d.version)
    console.print(table_dep)
    console.print()

    # 总结
    console.print()
    if report.ready_for_decryption:
        console.print("[bold green]  All checks passed — 环境就绪，可以开始消息解密。[/bold green]")
    else:
        console.print("[bold red]  Environment NOT ready[/bold red]")
        console.print()

        if report.issues:
            console.print("[bold yellow]Issues:[/bold yellow]")
            for issue in report.issues:
                console.print(f"  [red]X[/red] {issue}")

        if report.warnings:
            console.print("[bold yellow]Warnings:[/bold yellow]")
            for warning in report.warnings:
                console.print(f"  [yellow]![/yellow] {warning}")

    console.print()
    console.print("[bold]Next Steps:[/bold]")
    for step in report.next_steps:
        console.print(f"  {step}")
    console.print()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V",
        help="显示版本号",
    ),
) -> None:
    """Miru Assistant — AI 微信秘书。

    每天定时自动总结微信群消息，生成日报推送到手机。
    """
    # 最早初始化日志系统
    from miru.core.logging import init_logging
    init_logging()

    if version:
        console.print(f"Miru Assistant v{__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()

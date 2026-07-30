"""
Alap-Alap CLI

Typer application backing both ``python main.py <command>`` and the
``alap-alap`` console script.
"""

from __future__ import annotations

import contextlib
import json as jsonlib
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.config import config, find_config_file
from src.core import AlapAlap, solve_batch
from src.detector import SitekeyDetector
from src.logger import get_log_stats, setup_logger
from src.models import SolveResult
from src.sitekeys_db import sitekeys_db


def _force_utf8_output() -> None:
    """
    Make stdout/stderr UTF-8 safe.

    On Windows, redirecting output switches Python to the locale encoding
    (cp1252), so the emoji in this CLI's own panels raise UnicodeEncodeError as
    soon as a user pipes output to a file. Reconfiguring up front keeps
    ``python main.py solve ... > log.txt`` working.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # A detached or already-wrapped stream cannot be reconfigured; the
        # fallback is simply the platform default.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_output()

# Get version from package metadata
try:
    from importlib.metadata import version

    __version__ = version("alap-alap")
except Exception:
    __version__ = "unknown"

# Initialize logger
logger = setup_logger()

app = typer.Typer(
    name="alap-alap",
    help="🦅 Cloudflare Turnstile Captcha Solver",
    add_completion=False,
)
console = Console()

#: Packages the browser stack needs at runtime.
RUNTIME_PACKAGES = ("requests", "camoufox", "playwright")


def missing_packages() -> list[str]:
    """Return the runtime packages that are not installed."""
    import importlib.util

    missing = []
    for name in RUNTIME_PACKAGES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def ensure_dependencies(auto_install: bool = True) -> None:
    """
    Make sure the browser stack is installed.

    Called only by the commands that actually drive a browser. It used to run at
    import time, which meant ``main.py --help`` could trigger a pip install and a
    browser download.

    Args:
        auto_install: Install what is missing. When false, missing packages are
            reported and the command exits.
    """
    missing = missing_packages()
    if not missing:
        return

    if not auto_install:
        console.print(
            Panel(
                f"[red]Missing dependencies:[/red] {', '.join(missing)}\n\n"
                "Install them with:\n"
                "  [bold]pip install -r requirements.txt[/bold]\n"
                "  [bold]camoufox fetch[/bold]",
                title="Dependencies",
                border_style="red",
            )
        )
        raise typer.Exit(1)

    logger.info(f"Installing missing: {', '.join(missing)}")
    console.print(f"[yellow]Installing missing dependencies: {', '.join(missing)}[/yellow]")

    # requirements.txt sits at the repository root, one level above this package.
    requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
    try:
        if requirements.is_file():
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements), "--quiet"]
            )
        else:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Dependency install failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    if "camoufox" in missing or "playwright" in missing:
        logger.info("Installing browsers...")
        console.print("[yellow]Downloading browser (this can take a while)...[/yellow]")
        for command in ([sys.executable, "-m", "camoufox", "fetch"],):
            try:
                subprocess.check_call(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError as exc:
                console.print(f"[yellow]Warning: {' '.join(command)} failed ({exc})[/yellow]")

    logger.info("Setup complete!")
    console.print("[green]Setup complete![/green]")


def save_result(result: SolveResult, output_file: str | None = None) -> None:
    """Append a result to the results file as a JSON line."""
    filepath = output_file or config.storage.RESULTS_FILE
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(result.model_dump_json() + "\n")
    except OSError as exc:
        logger.error(f"Could not write result to {filepath}: {exc}")
        console.print(f"[red]Could not write {filepath}: {exc}[/red]")


def _spinner(description: str) -> Progress:
    """Build the shared spinner progress widget."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    )


def _truncate(value: str | None, length: int = 50) -> str:
    """Shorten a token for display."""
    if not value:
        return "-"
    return value if len(value) <= length else f"{value[:length]}..."


def _token_freshness(entry) -> str:
    """
    Describe whether a stored token is still usable.

    Turnstile tokens expire after roughly five minutes, so a stored token
    without a verdict on its age is misleading.
    """
    remaining = entry.token_expires_in
    if remaining is None:
        return "[dim]-[/dim]"
    if remaining > 0:
        return f"[green]fresh {remaining:.0f}s[/green]"
    return "[red]expired[/red]"


@app.command()
def solve(
    url: str = typer.Argument(help="URL to solve captcha on"),
    sitekey: str | None = typer.Option(None, "--sitekey", "-s", help="Known sitekey"),
    proxy: str | None = typer.Option(None, "--proxy", "-p", help="Proxy (user:pass@host:port)"),
    visible: bool = typer.Option(False, "--visible", "-v", help="Use visible browser mode"),
    retries: int = typer.Option(1, "--retries", "-r", help="Number of attempts"),
    timeout: float | None = typer.Option(
        None, "--timeout", "-t", help="Per-attempt time budget in seconds"
    ),
    output: str = typer.Option("results.txt", "--output", "-o", help="Output file"),
    as_json: bool = typer.Option(False, "--json", help="Print the raw result as JSON"),
    no_install: bool = typer.Option(
        False, "--no-install", help="Fail instead of auto-installing dependencies"
    ),
):
    """Solve Cloudflare Turnstile captcha."""
    ensure_dependencies(auto_install=not no_install)

    # A retries value below 1 used to leave the result unset and crash with an
    # AttributeError further down; treat it as a single attempt.
    attempts = max(1, retries)
    if retries < 1:
        console.print(f"[yellow]--retries {retries} is invalid, using 1[/yellow]")

    with _spinner("Solving captcha...") as progress:
        progress.add_task("Solving captcha...", total=None)
        try:
            with AlapAlap(proxy=proxy, timeout=timeout) as alap:
                if sitekey:
                    result = alap.solve_with_sitekey(
                        url, sitekey, invisible=not visible, retries=attempts, timeout=timeout
                    )
                else:
                    result = alap.solve(
                        url, invisible=not visible, retries=attempts, timeout=timeout
                    )
        except Exception as e:
            logger.error(f"Solve failed: {e}")
            result = {
                "success": False,
                "error": str(e),
                "token": None,
                "sitekey": sitekey,
                "time": 0.0,
                "attempts": 0,
            }

    sitekeys_db.record_result(url, result, tags=["cli"])
    save_result(SolveResult.from_outcome(url, result), output)

    if as_json:
        console.print_json(jsonlib.dumps({"url": url, **result}))

    if result["success"]:
        console.print(
            Panel(
                f"[green]✓ Success![/green]\n\n"
                f"[bold]Token:[/bold] {_truncate(result['token'])}\n"
                f"[bold]Sitekey:[/bold] {result['sitekey']}\n"
                f"[bold]Time:[/bold] {result['time']:.1f}s\n"
                f"[bold]Attempts:[/bold] {result.get('attempts', 1)}",
                title="Result",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[red]✗ Failed: {result['error']}[/red]",
                title="Result",
                border_style="red",
            )
        )
        raise typer.Exit(1)


@app.command()
def batch(
    source: Path = typer.Argument(
        help="File with one URL per line ('-' reads standard input)",
        exists=False,
    ),
    proxy: str | None = typer.Option(None, "--proxy", "-p", help="Proxy for every worker"),
    proxy_file: Path | None = typer.Option(
        None, "--proxy-file", help="File of proxies, assigned to workers round-robin"
    ),
    visible: bool = typer.Option(False, "--visible", "-v", help="Use visible browser mode"),
    retries: int = typer.Option(1, "--retries", "-r", help="Attempts per URL"),
    timeout: float | None = typer.Option(
        None, "--timeout", "-t", help="Per-attempt time budget in seconds"
    ),
    workers: int | None = typer.Option(
        None, "--workers", "-w", help="Parallel browsers (default: config.batch.MAX_WORKERS)"
    ),
    output: str = typer.Option("results.txt", "--output", "-o", help="Output file"),
    no_install: bool = typer.Option(
        False, "--no-install", help="Fail instead of auto-installing dependencies"
    ),
):
    """Solve many URLs from a file, in parallel."""
    ensure_dependencies(auto_install=not no_install)

    urls = _read_lines(source, "URL list")
    if not urls:
        console.print("[red]No URLs to process[/red]")
        raise typer.Exit(1)

    proxies = _read_lines(proxy_file, "proxy list") if proxy_file else None
    worker_count = workers if workers is not None else config.batch.MAX_WORKERS

    console.print(
        Panel(
            f"[bold]URLs:[/bold] {len(urls)}\n"
            f"[bold]Workers:[/bold] {min(worker_count, len(urls))}\n"
            f"[bold]Proxies:[/bold] {len(proxies) if proxies else (1 if proxy else 0)}\n"
            f"[bold]Attempts per URL:[/bold] {max(1, retries)}",
            title="Batch Solve",
            border_style="cyan",
        )
    )

    started = time.time()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Solving 0/{len(urls)}...", total=len(urls))
        done = 0

        def on_result(result: dict) -> None:
            nonlocal done
            done += 1
            mark = "✓" if result.get("success") else "✗"
            progress.update(
                task,
                advance=1,
                description=f"Solving {done}/{len(urls)}... last {mark}",
            )

        results = solve_batch(
            urls,
            proxy=proxy,
            proxies=proxies,
            invisible=not visible,
            retries=max(1, retries),
            timeout=timeout,
            workers=worker_count,
            on_result=on_result,
        )

    elapsed = time.time() - started
    succeeded = sum(1 for r in results if r.get("success"))

    for result in results:
        target = result.get("url", "")
        sitekeys_db.record_result(target, result, tags=["cli", "batch"])
        save_result(SolveResult.from_outcome(target, result), output)

    table = Table(title="Batch Results", show_header=True, header_style="bold cyan")
    table.add_column("URL", style="dim", overflow="fold")
    table.add_column("Status")
    table.add_column("Token")
    table.add_column("Time")

    for result in results:
        status = "[green]✓[/green]" if result.get("success") else "[red]✗[/red]"
        if result.get("success"):
            detail = _truncate(result.get("token"), 24)
        else:
            detail = result.get("error")
        table.add_row(
            result.get("url", "-"),
            status,
            str(detail),
            f"{result.get('time', 0.0):.1f}s",
        )

    console.print(table)
    console.print(
        Panel(
            f"[bold]Solved:[/bold] {succeeded}/{len(results)}\n"
            f"[bold]Total time:[/bold] {elapsed:.1f}s\n"
            f"[bold]Saved to:[/bold] {output}",
            title="Summary",
            border_style="green" if succeeded else "red",
        )
    )

    if not succeeded:
        raise typer.Exit(1)


def _read_lines(source: Path | None, label: str) -> list[str]:
    """Read non-empty, non-comment lines from a file or standard input."""
    if source is None:
        return []

    if str(source) == "-":
        raw = sys.stdin.read()
    else:
        if not source.is_file():
            console.print(f"[red]{label} not found: {source}[/red]")
            raise typer.Exit(1)
        try:
            raw = source.read_text(encoding="utf-8")
        except OSError as exc:
            console.print(f"[red]Could not read {source}: {exc}[/red]")
            raise typer.Exit(1) from exc

    return [line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")]


@app.command()
def detect(
    url: str = typer.Argument(help="URL to detect sitekey from"),
    proxy: str | None = typer.Option(None, "--proxy", "-p", help="Proxy (user:pass@host:port)"),
    output: str = typer.Option("results.txt", "--output", "-o", help="Output file"),
    no_install: bool = typer.Option(
        False, "--no-install", help="Fail instead of auto-installing dependencies"
    ),
):
    """Detect sitekey from URL without solving."""
    ensure_dependencies(auto_install=not no_install)

    with _spinner("Detecting sitekey...") as progress:
        progress.add_task("Detecting sitekey...", total=None)
        detector = SitekeyDetector(proxy=proxy)
        try:
            sitekey, method = detector.detect_with_method(url)
        finally:
            detector.close()

    if sitekey:
        # Save to sitekeys database
        sitekeys_db.add(sitekey, url, status="unknown", tags=["detected"])
        save_result(
            SolveResult(url=url, sitekey=sitekey, status="sitekey_only"),
            output,
        )
        console.print(
            Panel(
                f"[green]✓ Sitekey found:[/green] [bold]{sitekey}[/bold]\n"
                f"[bold]Method:[/bold] {method}",
                title="Detection",
                border_style="green",
            )
        )
    else:
        save_result(
            SolveResult(url=url, status="no_sitekey", error="Sitekey not found"),
            output,
        )
        console.print(
            Panel(
                "[red]✗ Sitekey not found[/red]",
                title="Detection",
                border_style="red",
            )
        )
        raise typer.Exit(1)


@app.command()
def sitekeys(
    action: str = typer.Argument(help="Action: list, search, export, stats, prune"),
    query: str | None = typer.Argument(None, help="Search query (for the search action)"),
    query_option: str | None = typer.Option(None, "--query", "-q", help="Search query"),
    status: str | None = typer.Option(
        None, "--status", help="Filter by status: active, inactive, unknown"
    ),
    export_format: str = typer.Option(
        "markdown", "--format", "-f", help="Export format: markdown, csv, json"
    ),
    output: str | None = typer.Option(None, "--output", "-o", help="Export destination file"),
    days: int | None = typer.Option(
        None, "--days", help="For prune: drop entries not seen in this many days"
    ),
    failed_only: bool = typer.Option(
        False, "--failed", help="For prune: only drop entries that never solved"
    ),
):
    """Manage sitekeys database."""
    # The README documents `sitekeys search etherscan`, so accept the query
    # positionally as well as via --query.
    search_term = query or query_option

    if action == "list":
        entries = sitekeys_db.get_all()
        if status:
            entries = [e for e in entries if e.status == status]
        if not entries:
            console.print("[yellow]No sitekeys in database[/yellow]")
            return

        table = Table(
            title=f"Sitekeys Database ({len(entries)} entries)",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Sitekey", style="dim")
        table.add_column("Platform")
        table.add_column("Domain")
        table.add_column("Status")
        table.add_column("Success Rate")
        table.add_column("Token")
        table.add_column("Tags")

        for entry in sorted(entries, key=lambda e: e.platform_name):
            rate = f"{entry.success_count}/{entry.solve_count}" if entry.solve_count > 0 else "-"
            tags = ", ".join(entry.tags) if entry.tags else "-"
            table.add_row(
                f"{entry.sitekey[:20]}...",
                entry.platform_name,
                entry.domain,
                f"{entry.status_icon} {entry.status}",
                rate,
                _token_freshness(entry),
                tags,
            )

        console.print(table)

    elif action == "search":
        if not search_term:
            console.print("[red]Please provide a search term[/red]")
            console.print("Usage: python main.py sitekeys search <query>")
            raise typer.Exit(1)

        entries = sitekeys_db.search(search_term)
        if not entries:
            console.print(f"[yellow]No results for '{search_term}'[/yellow]")
            return

        for entry in entries:
            console.print(
                f"• {entry.sitekey[:30]}... → {entry.domain} "
                f"({entry.status_icon} {entry.status}) [{entry.platform_name}]"
            )

    elif action == "export":
        fmt = export_format.lower()
        renderers = {
            "markdown": (sitekeys_db.export_markdown, "SITEKEYS.md"),
            "md": (sitekeys_db.export_markdown, "SITEKEYS.md"),
            "csv": (sitekeys_db.export_csv, "sitekeys.csv"),
            "json": (sitekeys_db.export_json, "sitekeys.json"),
        }
        if fmt not in renderers:
            console.print(f"[red]Unknown format: {export_format}[/red]")
            console.print(f"Available formats: {', '.join(sorted(renderers))}")
            raise typer.Exit(1)

        render, default_name = renderers[fmt]
        destination = output or default_name
        try:
            Path(destination).write_text(render(), encoding="utf-8")
        except OSError as exc:
            console.print(f"[red]Could not write {destination}: {exc}[/red]")
            raise typer.Exit(1) from exc

        console.print(
            Panel(
                f"[green]✓ Exported {len(sitekeys_db.get_all())} entries "
                f"to {destination}[/green]\n\nReady to share with the community!",
                title="Export",
                border_style="green",
            )
        )

    elif action == "stats":
        summary = sitekeys_db.stats()

        table = Table(title="Sitekeys Statistics", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="dim")
        table.add_column("Value")

        table.add_row("Total Sitekeys", str(summary["total_sitekeys"]))
        table.add_row("Active Sitekeys", str(summary["active_sitekeys"]))
        table.add_row("Inactive Sitekeys", str(summary["inactive_sitekeys"]))
        table.add_row("Unknown Sitekeys", str(summary["unknown_sitekeys"]))
        table.add_row("Distinct Domains", str(summary["total_domains"]))
        table.add_row("Total Solve Attempts", str(summary["total_solve_attempts"]))
        table.add_row("Successful Solves", str(summary["successful_solves"]))
        table.add_row(
            "Success Rate",
            f"{summary['success_rate'] * 100:.1f}%" if summary["total_solve_attempts"] else "N/A",
        )
        table.add_row("Avg Solve Time", f"{summary['avg_solve_time']}s")
        table.add_row("Unexpired Tokens", str(summary["fresh_tokens"]))

        console.print(table)

    elif action == "prune":
        if days is None and not failed_only:
            console.print("[red]Specify --days N and/or --failed[/red]")
            raise typer.Exit(1)

        removed = sitekeys_db.prune(older_than_days=days, only_failed=failed_only)
        console.print(
            Panel(
                f"[green]Removed {removed} entrie(s)[/green]\n"
                f"[bold]Remaining:[/bold] {len(sitekeys_db.get_all())}",
                title="Prune",
                border_style="green",
            )
        )

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Available actions: list, search, export, stats, prune")
        raise typer.Exit(1)


@app.command()
def health():
    """Check dependencies status."""
    import importlib.util

    table = Table(title="Health Check", show_header=True, header_style="bold cyan")
    table.add_column("Component", style="dim")
    table.add_column("Status")
    table.add_column("Note")

    checks = (
        ("camoufox", "pip install camoufox"),
        ("playwright", "pip install playwright"),
        ("rich", "pip install rich"),
        ("loguru", "pip install loguru"),
        ("pydantic", "pip install pydantic"),
        ("flask", "pip install flask"),
        ("tenacity", "pip install tenacity"),
        ("yaml", "pip install pyyaml"),
    )

    for name, remedy in checks:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if found:
            table.add_row(name, "[green]✓ OK[/green]", "")
        else:
            table.add_row(name, "[red]✗ MISSING[/red]", remedy)

    # Check the browser binary without launching it.
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)
        if executable.exists():
            table.add_row("chromium", "[green]✓ OK[/green]", "")
        else:
            table.add_row(
                "chromium", "[yellow]⚠ NOT INSTALLED[/yellow]", "playwright install chromium"
            )
    except Exception:
        table.add_row("chromium", "[yellow]⚠ NOT INSTALLED[/yellow]", "playwright install chromium")

    log_stats = get_log_stats()
    table.add_row(
        "logs",
        "[green]✓ OK[/green]",
        f"{log_stats['files']} files, {log_stats['total_size_mb']} MB",
    )

    table.add_row("sitekeys_db", "[green]✓ OK[/green]", f"{len(sitekeys_db.get_all())} entries")

    config_file = None
    # A broken config file should not stop the health report from rendering.
    with contextlib.suppress(Exception):
        config_file = find_config_file()
    table.add_row(
        "config",
        "[green]✓ OK[/green]",
        str(config_file) if config_file else "defaults + environment",
    )

    console.print(table)


@app.command()
def info():
    """Show project information."""
    log_stats = get_log_stats()
    summary = sitekeys_db.stats()

    console.print(
        Panel(
            "[bold cyan]🦅 Alap-Alap[/bold cyan]\n\n"
            "Cloudflare Turnstile Captcha Solver\n\n"
            f"[bold]Version:[/bold] {__version__}\n"
            f"[bold]Python:[/bold] {sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}\n"
            f"[bold]License:[/bold] MIT\n"
            f"[bold]Logs:[/bold] {log_stats['files']} files, {log_stats['total_size_mb']} MB\n"
            f"[bold]Sitekeys:[/bold] {summary['total_sitekeys']} in database "
            f"({summary['active_sitekeys']} active)\n"
            f"[bold]Solve rate:[/bold] {summary['success_rate'] * 100:.1f}% "
            f"of {summary['total_solve_attempts']} attempts\n\n"
            "[dim]Fast as a falcon, smart as a hunter[/dim]",
            title="Project Info",
            border_style="cyan",
        )
    )


@app.command(name="config")
def show_config(
    as_json: bool = typer.Option(False, "--json", help="Print as JSON"),
    section: str | None = typer.Option(None, "--section", "-s", help="Show one section only"),
):
    """Show the effective configuration and where it came from."""
    data = config.to_dict()

    if section:
        if section not in data:
            console.print(f"[red]Unknown section: {section}[/red]")
            console.print(f"Available: {', '.join(sorted(data))}")
            raise typer.Exit(1)
        data = {section: data[section]}

    if as_json:
        console.print_json(jsonlib.dumps(data, default=str))
        return

    try:
        config_file = find_config_file()
    except Exception as exc:
        config_file = None
        console.print(f"[yellow]Config file problem: {exc}[/yellow]")

    console.print(
        Panel(
            f"[bold]Config file:[/bold] {config_file or 'none (defaults + environment)'}\n"
            "[dim]Override any value with ALAP_<SECTION>_<FIELD>, "
            "e.g. ALAP_BROWSER_HTTP_TIMEOUT=20[/dim]",
            title="Configuration",
            border_style="cyan",
        )
    )

    for name, values in data.items():
        table = Table(title=name, show_header=True, header_style="bold cyan")
        table.add_column("Option", style="dim")
        table.add_column("Value", overflow="fold")
        table.add_column("Env override", style="dim")
        for key, value in values.items():
            table.add_row(key, str(value), f"ALAP_{name.upper()}_{key}")
        console.print(table)


@app.command()
def setup(
    no_install: bool = typer.Option(
        False, "--check-only", help="Only report what is missing, install nothing"
    ),
):
    """Install runtime dependencies and browsers."""
    ensure_dependencies(auto_install=not no_install)
    console.print(
        Panel(
            "[green]✓ All runtime dependencies are present[/green]",
            title="Setup",
            border_style="green",
        )
    )


@app.command()
def server(
    host: str | None = typer.Option(None, "--host", "-h", help="Host to bind"),
    port: int | None = typer.Option(None, "--port", "-p", help="Port to bind"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
):
    """Start REST API server."""
    from src.api.server import create_app

    bind_host = host or config.api.HOST
    bind_port = port or config.api.PORT
    auth_enabled = bool(config.api.KEY)
    exposed = bind_host not in ("127.0.0.1", "localhost", "::1")

    flask_app = create_app()

    notes = [
        f"[bold]URL:[/bold] http://{bind_host}:{bind_port}",
        f"[bold]Debug:[/bold] {debug}",
        f"[bold]Auth:[/bold] {'API key required' if auth_enabled else 'open (no key set)'}",
        f"[bold]Rate limit:[/bold] {config.api.RATE_LIMIT_REQUESTS} "
        f"per {config.api.RATE_LIMIT_WINDOW_S:.0f}s",
        f"[bold]Max concurrent solves:[/bold] {config.api.MAX_CONCURRENT_SOLVES}",
        "",
        "[dim]Endpoints: /, /health, /solve, /detect, /sitekeys, /stats[/dim]",
    ]

    if exposed and not auth_enabled:
        notes.insert(
            0,
            "[red]⚠ Bound off-loopback with no API key: anyone who can reach "
            "this port can drive the solver. Set ALAP_API_KEY.[/red]\n",
        )
    if debug:
        notes.insert(
            0,
            "[red]⚠ Debug mode exposes an interactive console. "
            "Never use it in production.[/red]\n",
        )

    console.print(
        Panel(
            "\n".join(notes),
            title="Alap-Alap API Server",
            border_style="red" if (exposed and not auth_enabled) or debug else "green",
        )
    )
    console.print(
        "[dim]This is Flask's development server. "
        "Put a WSGI server (gunicorn, waitress) in front for real traffic.[/dim]"
    )

    flask_app.run(host=bind_host, port=bind_port, debug=debug)


if __name__ == "__main__":
    app()

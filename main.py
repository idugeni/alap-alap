"""
Alap-Alap - Cloudflare Turnstile Captcha Solver

Main entry point for the application.
"""

import sys
import time
import subprocess
from typing import Optional
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from pydantic import BaseModel, ConfigDict

from src.config import config
from src.logger import setup_logger, get_log_stats
from src.sitekeys_db import sitekeys_db

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
    add_completion=False
)
console = Console()


def check_and_install():
    """Check dependencies and auto-install if missing."""
    missing = []

    try:
        import requests
    except ImportError:
        missing.append("requests")

    try:
        import camoufox
    except ImportError:
        missing.append("camoufox")

    try:
        import playwright
    except ImportError:
        missing.append("playwright")

    if missing:
        logger.info(f"Installing missing: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--quiet"])

        if "playwright" in missing:
            logger.info("Installing browsers...")
            subprocess.check_call([sys.executable, "-m", "camoufox", "fetch"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        logger.info("Setup complete!")


check_and_install()

from src.core import AlapAlap
from src.detector import SitekeyDetector


# Data models
class SolveResult(BaseModel):
    model_config = ConfigDict()

    url: str
    sitekey: Optional[str] = None
    token: Optional[str] = None
    status: str
    error: Optional[str] = None
    timestamp: str


def save_result(result: SolveResult, output_file: str = None):
    """Save result to results.txt as JSON line."""
    filepath = output_file or config.storage.RESULTS_FILE
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")


@app.command()
def solve(
    url: str = typer.Argument(help="URL to solve captcha on"),
    sitekey: Optional[str] = typer.Option(None, "--sitekey", "-s", help="Known sitekey"),
    proxy: Optional[str] = typer.Option(None, "--proxy", "-p", help="Proxy (user:pass@host:port)"),
    visible: bool = typer.Option(False, "--visible", "-v", help="Use visible browser mode"),
    retries: int = typer.Option(1, "--retries", "-r", help="Number of retry attempts"),
    output: str = typer.Option("results.txt", "--output", "-o", help="Output file")
):
    """Solve Cloudflare Turnstile captcha."""
    last_result = None

    for attempt in range(retries):
        if attempt > 0:
            logger.info(f"Retry attempt {attempt + 1}/{retries}")
            console.print(f"[yellow]Retry {attempt + 1}/{retries}...[/yellow]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Solving captcha...", total=None)

            try:
                with AlapAlap(proxy=proxy) as alap:
                    if sitekey:
                        result = alap.solve_with_sitekey(url, sitekey, invisible=not visible)
                    else:
                        result = alap.solve(url, invisible=not visible)
                progress.update(task, completed=True)
            except Exception as e:
                progress.update(task, completed=True)
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                result = {"success": False, "error": str(e), "token": None, "sitekey": sitekey}

        last_result = result

        # Record in sitekeys database
        if result.get("sitekey"):
            sitekeys_db.add(result["sitekey"], url, status="active" if result["success"] else "inactive")
            sitekeys_db.record_solve(
                result["sitekey"],
                result["success"],
                token=result.get("token", ""),
                solve_time=result.get("time", 0.0)
            )

        if result["success"]:
            break

        if attempt < retries - 1:
            # Check for rate limit or timeout errors
            error = result.get("error", "")
            is_rate_limit = "rate limit" in error.lower() or "429" in error
            is_timeout = "timeout" in error.lower()

            if is_rate_limit:
                delay = config.retry.RATE_LIMIT_DELAY
                logger.warning(f"Rate limited. Waiting {delay:.1f}s...")
            elif is_timeout:
                delay = min(config.retry.RETRY_DELAY_BASE * (2 ** attempt), config.retry.RETRY_DELAY_MAX)
                logger.warning(f"Timeout. Waiting {delay:.1f}s...")
            else:
                delay = min(config.retry.RETRY_DELAY_BASE * (2 ** attempt), config.retry.RETRY_DELAY_MAX)
                logger.info(f"Waiting {delay:.1f}s before retry...")

            time.sleep(delay)

    entry = SolveResult(
        url=url,
        sitekey=last_result.get("sitekey"),
        token=last_result.get("token"),
        status="success" if last_result["success"] else "failed",
        error=last_result.get("error"),
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    save_result(entry, output)

    if last_result["success"]:
        console.print(Panel(
            f"[green]✓ Success![/green]\n\n"
            f"[bold]Token:[/bold] {last_result['token'][:50]}...\n"
            f"[bold]Sitekey:[/bold] {last_result['sitekey']}\n"
            f"[bold]Time:[/bold] {last_result['time']:.1f}s",
            title="Result",
            border_style="green"
        ))
    else:
        console.print(Panel(
            f"[red]✗ Failed: {last_result['error']}[/red]",
            title="Result",
            border_style="red"
        ))
        raise typer.Exit(1)


@app.command()
def detect(
    url: str = typer.Argument(help="URL to detect sitekey from"),
    output: str = typer.Option("results.txt", "--output", "-o", help="Output file")
):
    """Detect sitekey from URL without solving."""

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Detecting sitekey...", total=None)
        detector = SitekeyDetector()
        sitekey = detector.detect(url)
        progress.update(task, completed=True)

    if sitekey:
        # Save to sitekeys database
        sitekeys_db.add(sitekey, url, status="unknown", tags=["detected"])

        entry = SolveResult(
            url=url,
            sitekey=sitekey,
            status="sitekey_only",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        save_result(entry, output)
        console.print(Panel(
            f"[green]✓ Sitekey found:[/green] [bold]{sitekey}[/bold]",
            title="Detection",
            border_style="green"
        ))
    else:
        entry = SolveResult(
            url=url,
            status="no_sitekey",
            error="Sitekey not found",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        save_result(entry, output)
        console.print(Panel(
            "[red]✗ Sitekey not found[/red]",
            title="Detection",
            border_style="red"
        ))


@app.command()
def sitekeys(
    action: str = typer.Argument(help="Action: list, search, export, stats"),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Search query")
):
    """Manage sitekeys database."""
    if action == "list":
        entries = sitekeys_db.get_all()
        if not entries:
            console.print("[yellow]No sitekeys in database[/yellow]")
            return

        table = Table(title=f"Sitekeys Database ({len(entries)} entries)", show_header=True, header_style="bold cyan")
        table.add_column("Sitekey", style="dim")
        table.add_column("Domain")
        table.add_column("Status")
        table.add_column("Success Rate")
        table.add_column("Tags")

        for entry in entries:
            rate = f"{entry.success_count}/{entry.solve_count}" if entry.solve_count > 0 else "-"
            tags = ", ".join(entry.tags) if entry.tags else "-"
            status_icon = {"active": "🟢", "inactive": "🔴", "unknown": "⚪"}.get(entry.status, "⚪")
            table.add_row(
                f"{entry.sitekey[:20]}...",
                entry.domain,
                f"{status_icon} {entry.status}",
                rate,
                tags
            )

        console.print(table)

    elif action == "search":
        if not query:
            console.print("[red]Please provide --query[/red]")
            return

        entries = sitekeys_db.search(query)
        if not entries:
            console.print(f"[yellow]No results for '{query}'[/yellow]")
            return

        for entry in entries:
            console.print(f"• {entry.sitekey[:30]}... → {entry.domain} ({entry.status})")

    elif action == "export":
        md = sitekeys_db.export_markdown()
        with open("SITEKEYS.md", "w", encoding="utf-8") as f:
            f.write(md)
        console.print(Panel(
            "[green]✓ Exported to SITEKEYS.md[/green]\n\n"
            "Ready to share with the community!",
            title="Export",
            border_style="green"
        ))

    elif action == "stats":
        entries = sitekeys_db.get_all()
        active = sitekeys_db.get_active()
        total_solves = sum(e.solve_count for e in entries)
        total_success = sum(e.success_count for e in entries)

        table = Table(title="Sitekeys Statistics", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="dim")
        table.add_column("Value")

        table.add_row("Total Sitekeys", str(len(entries)))
        table.add_row("Active Sitekeys", str(len(active)))
        table.add_row("Total Solve Attempts", str(total_solves))
        table.add_row("Successful Solves", str(total_success))
        table.add_row("Success Rate", f"{total_success/total_solves*100:.1f}%" if total_solves > 0 else "N/A")

        console.print(table)

    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        console.print("Available actions: list, search, export, stats")


@app.command()
def health():
    """Check dependencies status."""
    table = Table(title="Health Check", show_header=True, header_style="bold cyan")
    table.add_column("Component", style="dim")
    table.add_column("Status")
    table.add_column("Note")

    # Check camoufox
    try:
        import camoufox
        table.add_row("camoufox", "[green]✓ OK[/green]", "")
    except ImportError:
        table.add_row("camoufox", "[red]✗ MISSING[/red]", "pip install camoufox")

    # Check playwright
    try:
        import playwright
        table.add_row("playwright", "[green]✓ OK[/green]", "")
    except ImportError:
        table.add_row("playwright", "[red]✗ MISSING[/red]", "pip install playwright")

    # Check chromium
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium
        table.add_row("chromium", "[green]✓ OK[/green]", "")
    except Exception:
        table.add_row("chromium", "[yellow]⚠ NOT INSTALLED[/yellow]", "playwright install chromium")

    # Check rich
    try:
        import rich
        table.add_row("rich", "[green]✓ OK[/green]", "")
    except ImportError:
        table.add_row("rich", "[red]✗ MISSING[/red]", "pip install rich")

    # Check loguru
    try:
        import loguru
        table.add_row("loguru", "[green]✓ OK[/green]", "")
    except ImportError:
        table.add_row("loguru", "[red]✗ MISSING[/red]", "pip install loguru")

    # Check pydantic
    try:
        import pydantic
        table.add_row("pydantic", "[green]✓ OK[/green]", "")
    except ImportError:
        table.add_row("pydantic", "[red]✗ MISSING[/red]", "pip install pydantic")

    # Log stats
    log_stats = get_log_stats()
    table.add_row("logs", "[green]✓ OK[/green]", f"{log_stats['files']} files, {log_stats['total_size_mb']} MB")

    # Sitekeys DB stats
    sitekeys_count = len(sitekeys_db.get_all())
    table.add_row("sitekeys_db", "[green]✓ OK[/green]", f"{sitekeys_count} entries")

    console.print(table)


@app.command()
def info():
    """Show project information."""
    import sys as _sys
    log_stats = get_log_stats()
    sitekeys_count = len(sitekeys_db.get_all())

    panel = Panel(
        "[bold cyan]🦅 Alap-Alap[/bold cyan]\n\n"
        "Cloudflare Turnstile Captcha Solver\n\n"
        f"[bold]Version:[/bold] {__version__}\n"
        f"[bold]Python:[/bold] {_sys.version_info.major}.{_sys.version_info.minor}+\n"
        f"[bold]License:[/bold] MIT\n"
        f"[bold]Logs:[/bold] {log_stats['files']} files, {log_stats['total_size_mb']} MB\n"
        f"[bold]Sitekeys:[/bold] {sitekeys_count} in database\n\n"
        "[dim]Fast as a falcon, smart as a hunter[/dim]",
        title="Project Info",
        border_style="cyan"
    )
    console.print(panel)


if __name__ == "__main__":
    app()

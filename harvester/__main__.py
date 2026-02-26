"""
Layer Harvester — entry point.

Reads WMS capabilities JSON files from input/, extracts hazardlookup layers,
and writes an Excel workbook per group to output/.

Usage:
    python -m harvester                 # base output (no PDF columns)
    python -m harvester --usage pdf     # includes PDF V2 column and breakdown
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import openpyxl
from rich.console import Console, Group
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.panel import Panel
from rich import box

import harvester.fetcher as fetcher
from harvester.core import (
    INPUT_DIR, OUTPUT_DIR, ENVS_DIR, BASE_COLUMNS, NO_PDF_LABEL,
    find_hazard_layers, extract_row,
    write_sheet, write_legend_sheet, collect_groups,
)

console = Console()

# Project root — mirrors the logic in core.py so relative display paths work
# identically whether running from source or as a PyInstaller bundle.
if getattr(sys, "frozen", False):
    _ROOT = Path.cwd()
else:
    _ROOT = Path(__file__).parent.parent


# ── Summary table (UI concern — lives here, not in core/pdf) ─────────────────

def build_summary_table(summary_rows: list, all_pdf_types: list, usage_pdf: bool) -> Table:
    table = Table(
        title="[bold]Extraction Summary[/bold]",
        title_justify="left",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold white on dark_blue",
        show_lines=True,
    )
    table.add_column("File",         style="cyan",  no_wrap=True)
    table.add_column("Total Layers", style="white", justify="right")

    if usage_pdf:
        for pdf_type in all_pdf_types:
            style = "dim" if pdf_type == NO_PDF_LABEL else "magenta"
            label = "No keywords to be included in PDF found" if pdf_type == NO_PDF_LABEL else pdf_type.title()
            table.add_column(label, style=style, justify="right")

    for row in summary_rows:
        cells = [row["fname"], str(row["total"])]
        if usage_pdf:
            cells += [str(row["pdf_counts"].get(t, 0)) for t in all_pdf_types]
        table.add_row(*cells)

    return table


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract hazardlookup layers from WMS capabilities JSON files.",
    )
    parser.add_argument(
        "--mode",
        choices=["pdf"],
        default=None,
        help="Output mode. Pass 'pdf' to include PDF V2 columns in the Excel and summary.",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        dest="no_fetch",
        help="Skip fetching from envs/ even if credential files are present.",
    )
    parser.add_argument(
        "--env",
        action="append",
        dest="env_files",
        metavar="PATH",
        help=(
            "Path to a specific .local.env file to fetch. "
            "Can be repeated for multiple environments. "
            "Takes precedence over auto-scanning envs/."
        ),
    )
    args = parser.parse_args()
    usage_pdf  = args.mode == "pdf"
    usage_slug = args.mode if args.mode else "base"
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Load PDF module only when needed
    pdf = None
    if usage_pdf:
        import harvester.pdf as pdf

    columns = pdf.active_columns() if usage_pdf else BASE_COLUMNS

    OUTPUT_DIR.mkdir(exist_ok=True)

    _prog_cols = (
        SpinnerColumn(),
        BarColumn(bar_width=30),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TextColumn("[bold blue]{task.description}"),
    )

    # ── Source detection ──────────────────────────────────────────────────────
    if args.env_files:
        all_env_entries = [fetcher.env_entry_from_path(Path(p)) for p in args.env_files]
    else:
        all_env_entries = fetcher.scan_envs(ENVS_DIR)

    # Build group → hostname slug map from BASE_URL (or LOGIN_URL as fallback).
    group_slugs: dict[str, str] = {}
    for grp, _env_name, env_dict in all_env_entries:
        if grp not in group_slugs:
            raw = env_dict.get("BASE_URL") or env_dict.get("LOGIN_URL", "")
            slug = fetcher.url_slug(raw)
            if slug:
                group_slugs[grp] = slug

    use_envs = bool(all_env_entries) and not args.no_fetch
    fetch_results: list[tuple[str, str, Path | None, str | None]] = []

    # ── Fetch phase ───────────────────────────────────────────────────────────
    if use_envs:
        n = len(all_env_entries)
        console.print(f"[bold cyan]Found {n} env file(s) → fetching capabilities…[/bold cyan]")
        time.sleep(0.1)
        fetch_prog = Progress(*_prog_cols, console=console)
        with Live(fetch_prog, console=console, refresh_per_second=15):
            task = fetch_prog.add_task("Fetching", total=n)
            for group, env_name, env_dict in all_env_entries:
                fetch_prog.update(
                    task,
                    description=f"[bold blue]{group}/{env_name}[/bold blue]",
                )
                saved, err = fetcher.fetch_capabilities(group, env_name, env_dict, INPUT_DIR)
                fetch_results.append((group, env_name, saved, err))
                fetch_prog.advance(task)
        for group, env_name, saved, err in fetch_results:
            if err:
                console.print(f"  [bold red]✗[/bold red] {group}/{env_name}  [dim red]{err}[/dim red]")
            else:
                console.print(f"  [bold green]✓[/bold green] {group}/{env_name}")
        console.print()
    elif not all_env_entries and not args.no_fetch:
        console.print("[yellow]No env files found in envs/ — falling back to input/ JSON files…[/yellow]")
        console.print()

    # ── Resolve groups to harvest ─────────────────────────────────────────────
    if args.env_files and fetch_results:
        groups: dict[str, list[Path]] = {}
        for _g, _e, saved, _err in fetch_results:
            if saved:
                groups.setdefault(_g, []).append(saved)
    else:
        groups = collect_groups(INPUT_DIR)

    if not groups:
        if not all_env_entries and not args.no_fetch:
            console.print("[bold red]Nothing to do: no env files in envs/ and no JSON files in input/.[/bold red]")
        else:
            console.print("[bold red]No JSON files found in input/[/bold red]")
        return

    total_files = sum(len(v) for v in groups.values())

    mode_tag = " [bold yellow]· PDF mode[/bold yellow]" if usage_pdf else ""
    console.print(Panel.fit(
        f"[bold cyan]Layer Harvester[/bold cyan]{mode_tag}\n"
        "[dim]Extracting [bold]hazardlookup[/bold] layers from WMS capabilities files[/dim]",
        border_style="cyan",
    ))
    time.sleep(0.1)
    console.print()

    saved_files   = []
    group_results = []

    overall_prog = Progress(*_prog_cols, console=console)
    files_prog   = Progress(*_prog_cols, console=console)

    with Live(
        Group(overall_prog, Rule(style="dim cyan"), files_prog),
        console=console,
        refresh_per_second=15,
    ):
        overall = overall_prog.add_task("Overall", total=total_files)
        time.sleep(0.1)

        for group_name, json_files in groups.items():
            label = f"[bold dim]input/{group_name}/[/bold dim]" if group_name else "[bold dim]input/[/bold dim]"
            files_prog.add_task(label, total=1, completed=1)
            time.sleep(0.1)

            wb            = openpyxl.Workbook()
            wb.remove(wb.active)
            summary_rows  = []
            all_pdf_types = []

            for json_path in json_files:
                file_task = files_prog.add_task(f"  [cyan]{json_path.name}[/cyan]", total=3)
                time.sleep(0.1)

                # Step 1 — parse
                files_prog.update(file_task, description=f"  [cyan]{json_path.name}[/cyan]  [dim]parsing…[/dim]")
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                time.sleep(0.1)
                files_prog.advance(file_task)

                # Step 2 — extract
                files_prog.update(file_task, description=f"  [cyan]{json_path.name}[/cyan]  [dim]extracting layers…[/dim]")
                layers = []
                find_hazard_layers(data, layers)
                rows = [extract_row(layer) for layer in layers]
                global_count = sum(1 for r in rows if r["_global"])
                time.sleep(0.1)
                files_prog.advance(file_task)

                # Step 3 — write sheet
                files_prog.update(file_task, description=f"  [cyan]{json_path.name}[/cyan]  [dim]writing sheet…[/dim]")
                ws = wb.create_sheet(title=json_path.stem[:31])
                write_sheet(ws, rows, columns)
                time.sleep(0.1)
                files_prog.advance(file_task)

                pdf_counts: dict[str, int] = {}
                if usage_pdf:
                    file_pdf_types, pdf_counts = pdf.collect_pdf_data(rows)
                    for t in file_pdf_types:
                        if t not in all_pdf_types:
                            all_pdf_types.append(t)

                files_prog.update(file_task, description=f"  [green]✓[/green] [cyan]{json_path.name}[/cyan]")
                overall_prog.advance(overall)
                time.sleep(0.1)

                summary_rows.append({
                    "fname":      json_path.name,
                    "total":      len(rows),
                    "pdf_counts": pdf_counts,
                })

            # Determine output path for this group.
            # Use the BASE_URL hostname slug when available; fall back to group name.
            name_slug = group_slugs.get(group_name, group_name or "base")
            mode_suffix = "_pdf" if usage_pdf else ""
            out_dir = OUTPUT_DIR / name_slug if name_slug else OUTPUT_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{timestamp}_{name_slug}{mode_suffix}_layers.xlsx"

            if usage_pdf:
                all_pdf_types.sort(key=pdf.sort_key)

            write_legend_sheet(wb, pdf.PDF_COLUMN_DESCRIPTION if usage_pdf else None)
            wb.save(out_file)

            group_results.append({
                "group":         group_name or "(root)",
                "out_file":      out_file,
                "summary_rows":  summary_rows,
                "all_pdf_types": all_pdf_types,
            })
            saved_files.append(out_file)

    time.sleep(0.1)

    # ── Per-group summaries ──────────────────────────────────────────────────
    for result in group_results:
        console.print()
        console.print(f"\n[bold bright_yellow]  ◆  {result['group'].upper()}  ◆[/bold bright_yellow]")
        console.rule(style="yellow")
        console.print(build_summary_table(result["summary_rows"], result["all_pdf_types"], usage_pdf))
        rel = result["out_file"].relative_to(_ROOT)
        console.print(f"  [bold green]✓ Saved:[/bold green] [underline]{rel}[/underline]")
        time.sleep(0.1)

    console.print()

    # ── Open prompt ──────────────────────────────────────────────────────────
    if saved_files:
        count = len(saved_files)
        prompt = (
            "[bold cyan]Open the output file?[/bold cyan]"
            if count == 1 else
            f"[bold cyan]Open all {count} output files?[/bold cyan]"
        )
        try:
            answer = console.input(f"{prompt} [dim](y/n)[/dim] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "yes"):
            import subprocess
            for f in saved_files:
                subprocess.run(["open", str(f)], check=False)
            console.print("[dim]Opening…[/dim]")
        else:
            console.print("[dim]Done.[/dim]")
    else:
        console.print("[dim]Done.[/dim]")
    console.print()


if __name__ == "__main__":
    main()

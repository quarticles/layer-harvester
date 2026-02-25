"""
Layer Harvester — entry point.

Reads WMS capabilities JSON files from input/, extracts hazardlookup layers,
and writes an Excel workbook per group to output/.

Usage:
    python -m harvester                 # base output (no PDF columns)
    python -m harvester --usage pdf     # includes PDF V2 column and breakdown
"""

import argparse
import json
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

from harvester.core import (
    INPUT_DIR, OUTPUT_DIR, BASE_COLUMNS, NO_PDF_LABEL,
    find_hazard_layers, extract_row,
    write_sheet, write_legend_sheet, collect_groups,
)

console = Console()

# Project root — one level above this package
_ROOT = Path(__file__).parent.parent


# ── Summary table (UI concern — lives here, not in core/pdf_mode) ─────────────

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
        "--usage",
        choices=["pdf"],
        default=None,
        help="Output mode. Pass 'pdf' to include PDF V2 columns in the Excel and summary.",
    )
    args = parser.parse_args()
    usage_pdf  = args.usage == "pdf"
    usage_slug = args.usage if args.usage else "base"
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Load PDF module only when needed
    pdf = None
    if usage_pdf:
        import harvester.pdf_mode as pdf

    columns = pdf.active_columns() if usage_pdf else BASE_COLUMNS

    OUTPUT_DIR.mkdir(exist_ok=True)

    groups = collect_groups(INPUT_DIR)
    if not groups:
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

    _prog_cols = (
        SpinnerColumn(),
        BarColumn(bar_width=30),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TextColumn("[bold blue]{task.description}"),
    )
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

            # Determine output path for this group
            out_dir = OUTPUT_DIR / group_name if group_name else OUTPUT_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{timestamp}_{usage_slug}_layers.xlsx"

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

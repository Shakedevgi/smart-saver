"""Smart Saver CLI.

Three sub-commands:

    python cli.py ingest <url> [flags]      # Step 1+2+3: extract → analyze → store
    python cli.py search "<query>" [flags]  # Step 3: semantic search across stored items
    python cli.py categories                # Step 3: list every category the store knows

Examples:
    python cli.py ingest "https://en.wikipedia.org/wiki/FastAPI"
    python cli.py ingest "<url>" --category "Tech Tools" --no-store
    python cli.py search "vietnam waterfalls" --limit 3
    python cli.py search "python web frameworks" --category "Tech Tools"
    python cli.py categories
"""

from __future__ import annotations

import json
import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from src.analyzers import LLMAnalyzer
from src.config import settings
from src.extractors import VideoExtractor
from src.logger import get_logger
from src.orchestrator import IngestionOrchestrator
from src.schemas import AnalysisResult, IngestionResult, SearchHit, SourceType

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()
logger = get_logger("cli")


# ============================================================== render helpers
def _extraction_table(result: IngestionResult) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan")
    table.add_column()

    table.add_row("URL", result.url)
    table.add_row("Source type", result.source_type.value)

    if result.article is not None:
        a = result.article
        table.add_row("Title", a.title or "—")
        table.add_row("Author", a.author or "—")
        table.add_row("Site", a.site_name or "—")
        table.add_row("Publish date", a.publish_date or "—")
        table.add_row("Word count", str(a.word_count))

    if result.video is not None:
        v = result.video
        table.add_row("Title", v.title or "—")
        table.add_row("Uploader", v.uploader or "—")
        table.add_row("Duration", f"{v.duration_sec:.1f}s" if v.duration_sec else "—")
        table.add_row("Detected language", v.detected_language or "—")
        table.add_row("Transcript chars", str(len(v.transcript)))
        table.add_row("OCR frames", str(v.frames_sampled))
        table.add_row("OCR unique lines", str(len(v.ocr_text.splitlines()) if v.ocr_text else 0))

    if result.error:
        table.add_row("Error", f"[red]{result.error}[/red]")
    return table


def _analysis_table(analysis: AnalysisResult) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold magenta")
    table.add_column()

    cat_render = f"[bold]{analysis.suggested_category}[/bold]"
    if analysis.is_uncertain:
        cat_render += "  [yellow](uncertain)[/yellow]"
    table.add_row("Suggested category", cat_render)

    if analysis.is_uncertain and analysis.alternative_categories:
        table.add_row("Alternatives", "  •  ".join(analysis.alternative_categories))

    table.add_row("Summary", analysis.summary_one_liner)

    if analysis.key_insights:
        bullets = "\n".join(f"• {kp}" for kp in analysis.key_insights)
        table.add_row("Key insights", bullets)

    ents = analysis.extracted_entities.model_dump()
    if ents.get("price"):
        table.add_row("Price", str(ents["price"]))
    if ents.get("location"):
        table.add_row("Location", str(ents["location"]))
    if ents.get("technologies"):
        table.add_row("Technologies", ", ".join(ents["technologies"]))

    extras = {k: v for k, v in ents.items() if k not in {"price", "location", "technologies"}}
    if extras:
        table.add_row("Other entities", json.dumps(extras, ensure_ascii=False))
    return table


def _print_ingestion(result: IngestionResult) -> None:
    console.print(
        Panel.fit(_extraction_table(result), title="Ingestion summary", border_style="cyan"),
    )
    if result.analysis is not None:
        border = "yellow" if result.analysis.is_uncertain else "magenta"
        title = "LLM analysis" + (" — needs user disambiguation" if result.analysis.is_uncertain else "")
        console.print(Panel.fit(_analysis_table(result.analysis), title=title, border_style=border))

    text = result.aggregated_text
    if not text:
        console.print("[yellow]No text was extracted.[/yellow]")
        return
    console.print(Rule("Aggregated text (LLM input)"))
    preview = text if len(text) <= 4000 else text[:4000] + f"\n\n… [+{len(text) - 4000} more chars]"
    console.print(preview)


def _print_search(query: str, hits: list[SearchHit], category: str | None) -> None:
    if not hits:
        scope = f" in category {category!r}" if category else ""
        console.print(f"[yellow]No matches for[/yellow] {query!r}{scope}.")
        return

    table = Table(title=f"Search: {query!r}" + (f"  (category={category!r})" if category else ""), show_lines=False)
    table.add_column("#", style="bold", width=2)
    table.add_column("dist", justify="right", style="dim")
    table.add_column("category", style="magenta")
    table.add_column("summary")
    table.add_column("url", style="cyan")

    for idx, hit in enumerate(hits, start=1):
        dist = f"{hit.distance:.3f}" if hit.distance is not None else "—"
        table.add_row(
            str(idx),
            dist,
            hit.category or "—",
            (hit.summary or hit.document[:80] + ("…" if len(hit.document) > 80 else "")),
            hit.url,
        )
    console.print(table)


# ===================================================================== commands
@app.command()
def ingest(
    url: str = typer.Argument(..., help="URL of an article or video to ingest."),
    as_json: bool = typer.Option(False, "--json", help="Emit the full IngestionResult as JSON instead of a Rich panel."),
    analyze: bool = typer.Option(True, "--analyze/--no-analyze", help="Run the LLM analyzer after extraction."),
    store: bool = typer.Option(True, "--store/--no-store", help="Persist the result to the vector store."),
    ollama_model: str | None = typer.Option(None, "--ollama-model", help="Override the Ollama model name (default from settings)."),
    category: list[str] = typer.Option(None, "--category", help="Override the auto-pulled existing categories (repeat flag for multiple)."),
    whisper_model: str | None = typer.Option(None, "--whisper-model", help="Override Whisper model: tiny|base|small|medium|large-v3."),
    frame_interval: float | None = typer.Option(None, "--frame-interval", help="Override frame sampling interval (seconds)."),
    ocr_lang: list[str] = typer.Option(None, "--ocr-lang", help="Override OCR languages (repeat flag for multi-language)."),
) -> None:
    """Run the full extract → analyze → store pipeline for one URL."""

    if whisper_model:
        settings.whisper_model = whisper_model
    if ocr_lang:
        settings.ocr_languages = ocr_lang
    if frame_interval is not None:
        settings.frame_sample_interval_sec = frame_interval
    if ollama_model:
        settings.ollama_model = ollama_model

    video_extractor = VideoExtractor(frame_interval_sec=frame_interval)
    llm_analyzer = LLMAnalyzer() if analyze else None
    orchestrator = IngestionOrchestrator(
        video_extractor=video_extractor,
        llm_analyzer=llm_analyzer,
    )
    result = orchestrator.ingest(
        url,
        analyze=analyze,
        store=store,
        existing_categories=category or None,
    )

    if as_json:
        # aggregated_text is a @computed_field, so model_dump includes it.
        json.dump(result.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    _print_ingestion(result)
    if result.source_type is SourceType.UNKNOWN or result.error:
        raise typer.Exit(code=1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural-language search query."),
    limit: int = typer.Option(5, "--limit", "-n", help="How many hits to return."),
    category: str | None = typer.Option(None, "--category", help="Restrict the search to a single category."),
    as_json: bool = typer.Option(False, "--json", help="Emit the hits as JSON instead of a Rich table."),
) -> None:
    """Semantic search across everything that has been ingested into the store."""
    orchestrator = IngestionOrchestrator()
    hits = orchestrator.search(query, limit=limit, category=category)

    if as_json:
        payload = [h.model_dump(mode="json") for h in hits]
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    _print_search(query, hits, category)


@app.command()
def categories(
    as_json: bool = typer.Option(False, "--json", help="Emit the list as JSON instead of a Rich panel."),
) -> None:
    """List every distinct category the store has seen so far."""
    orchestrator = IngestionOrchestrator()
    cats = orchestrator.list_categories()

    if as_json:
        json.dump(cats, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return

    if not cats:
        console.print("[yellow]No items have been ingested yet — store is empty.[/yellow]")
        return
    table = Table(title=f"Known categories ({len(cats)})", show_header=False)
    table.add_column(style="bold magenta")
    for c in cats:
        table.add_row(c)
    console.print(table)


if __name__ == "__main__":
    app()

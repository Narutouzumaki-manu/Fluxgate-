"""Download and verify the all-MiniLM-L6-v2 sentence-transformer model.

Usage::

    python scripts/download_models.py [--model-dir ./models/all-MiniLM-L6-v2]

Contract (TOOLS_AND_REQUIREMENTS.md §4):
  - Idempotent: safe to re-run; skips download when files and checksums match.
  - Prints SHA-256 of each downloaded file.
  - Refuses to run if HF_HUB_OFFLINE=1 and files are missing.
  - Exits with code != 0 on any error or checksum mismatch.
  - After a successful download, prints the reminder to set HF_HUB_OFFLINE=1.

Pinned revision: the REVISION constant below must be updated whenever the model
is intentionally upgraded (open a contract-change PR if the embedding dim changes).
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="download_models",
    help="Download and verify FluxGate model files (all-MiniLM-L6-v2).",
    add_completion=False,
)
console = Console()

# ---------------------------------------------------------------------------
# Pinned model revision (commit SHA from huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
# Update this when intentionally upgrading the model (see TOOLS_AND_REQUIREMENTS.md §4).
# ---------------------------------------------------------------------------
MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "8b3219a92973c328a8e22fadcfa821b5dc75636a"  # verify before tagging Gate 1

# Files we expect to be present after a successful download.
# SHA-256 values are populated after first download and committed.
# Leave as None if not yet known; download will warn but not fail on first run.
EXPECTED_FILES: dict[str, str | None] = {
    "config.json": None,
    "tokenizer_config.json": None,
    "tokenizer.json": None,
    "vocab.txt": None,
    "pytorch_model.bin": None,  # or model.safetensors — whichever is present
    "sentence_bert_config.json": None,
    "modules.json": None,
    "1_Pooling/config.json": None,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@app.command()
def main(
    model_dir: Path = typer.Option(
        Path("./models/all-MiniLM-L6-v2"),
        "--model-dir",
        help="Local directory to save the model.",
        writable=True,
    ),
    force: bool = typer.Option(False, "--force", help="Re-download even if files exist."),
) -> None:
    """Download sentence-transformers/all-MiniLM-L6-v2 for offline use."""

    offline = os.environ.get("HF_HUB_OFFLINE", "0") == "1"
    if offline and not model_dir.exists():
        console.print(
            "[bold red]ERROR:[/] HF_HUB_OFFLINE=1 is set but the model directory does not exist.\n"
            f"       Expected: {model_dir.resolve()}\n"
            "       Run this script without HF_HUB_OFFLINE=1 to download first.",
            highlight=False,
        )
        raise typer.Exit(1) from None

    if offline:
        console.print(
            f"[yellow]HF_HUB_OFFLINE=1 — skipping download, verifying local files at {model_dir}[/]"
        )
        _verify_local(model_dir)
        return

    try:
        from huggingface_hub import snapshot_download  # type: ignore[import-untyped]
    except ImportError:
        console.print(
            "[bold red]ERROR:[/] huggingface_hub is not installed.\n"
            "       Install it with: uv sync --extra dev  (it comes with sentence-transformers)",
            highlight=False,
        )
        raise typer.Exit(1) from None

    if model_dir.exists() and any(model_dir.iterdir()) and not force:
        console.print(f"[green]Model directory already exists:[/] {model_dir.resolve()}")
        console.print("Re-verifying checksums (use --force to re-download)…")
        _verify_local(model_dir)
        return

    console.print(f"[bold]Downloading[/] {MODEL_REPO} @ {REVISION[:12]}…")
    t0 = time.monotonic()

    local_dir = snapshot_download(
        repo_id=MODEL_REPO,
        revision=REVISION,
        local_dir=str(model_dir),
        local_dir_use_symlinks=False,
    )

    elapsed = time.monotonic() - t0
    console.print(f"[green]Download complete[/] in {elapsed:.1f}s → {local_dir}")

    _verify_local(Path(local_dir))

    console.print(
        "\n[bold yellow]REMINDER:[/] Set [bold]HF_HUB_OFFLINE=1[/] in your .env "
        "to prevent surprise network calls at runtime.\n"
        "          Add to .env:  HF_HUB_OFFLINE=1\n"
        "          Or export in shell: export HF_HUB_OFFLINE=1"
    )


def _verify_local(model_dir: Path) -> None:
    """Print SHA-256 of key files; warn if expected files are missing."""
    table = Table(title=f"Model files in {model_dir.resolve()}")
    table.add_column("File", style="cyan")
    table.add_column("SHA-256 (first 16 chars)", style="dim")
    table.add_column("Status")

    any_missing = False
    for rel, _expected_sha in EXPECTED_FILES.items():
        p = model_dir / rel
        if not p.exists():
            # Try safetensors alternative for the main weights file
            if rel == "pytorch_model.bin":
                alt = model_dir / "model.safetensors"
                if alt.exists():
                    sha = sha256_file(alt)
                    table.add_row("model.safetensors", sha[:16], "[green]OK (safetensors)[/]")
                    continue
            table.add_row(rel, "—", "[yellow]MISSING[/]")
            any_missing = True
            continue
        sha = sha256_file(p)
        status = "[green]OK[/]"
        if _expected_sha and sha != _expected_sha:
            status = f"[bold red]MISMATCH (expected {_expected_sha[:16]})[/]"
            any_missing = True
        table.add_row(rel, sha[:16], status)

    console.print(table)

    if any_missing:
        console.print(
            "[bold red]One or more expected files are missing or have wrong checksums.[/]"
        )
        console.print("Re-run without --model-dir modifications, or use --force to re-download.")
        raise typer.Exit(1) from None

    # Quick sanity: load the model and embed a test sentence.
    _smoke_test(model_dir)


def _smoke_test(model_dir: Path) -> None:
    """Load the model and verify it produces a 384-dim unit vector."""
    console.print("Running embedding smoke-test…", end=" ")
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        model = SentenceTransformer(str(model_dir), local_files_only=True)
        vec = model.encode("FluxGate smoke test", normalize_embeddings=True)
        vec = np.asarray(vec, dtype=np.float32)
        assert vec.shape == (384,), f"unexpected shape {vec.shape}"
        norm = float(np.linalg.norm(vec))
        assert 0.999 < norm < 1.001, f"unexpected norm {norm}"
        console.print(f"[green]PASS[/] shape={vec.shape}, norm={norm:.6f}")
    except Exception as exc:
        console.print(f"[bold red]FAIL:[/] {exc}")
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    app()

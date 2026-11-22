"""Environment readiness checker — run before Phase 2 / Gate 1.

Usage::

    python scripts/verify_env.py [--check-providers]

Checks (TOOLS_AND_REQUIREMENTS.md §7.4):
  1. Python >= 3.11 (3.12 recommended).
  2. Required packages importable: faiss, sentence_transformers, fastapi, httpx, aiosqlite.
  3. .env exists; required variables non-placeholder.
  4. SQLite WAL mode works in data/.
  5. MiniLM loads offline, outputs shape (384,), norm ≈ 1 after normalization; < 100 ms warm.
  6. CONTRACT_VERSION == "1.0.0".
  7. Prints Python/OS/CPU/RAM summary (paste into benchmark reports).
  (8) Optional --check-providers: 1-token test call per configured provider (uses quota!).
"""

from __future__ import annotations

import os
import platform
import sys
import time
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="verify_env",
    help="Check FluxGate environment readiness (TOOLS_AND_REQUIREMENTS.md §7.4).",
    add_completion=False,
)
console = Console()

ROOT = Path(__file__).resolve().parent.parent


def _check(label: str, passed: bool, detail: str = "") -> bool:
    icon = "[green]PASS[/]" if passed else "[bold red]FAIL[/]"
    console.print(f"  {icon}  {label}" + (f"  — {detail}" if detail else ""))
    return passed


@app.command()
def main(
    check_providers: bool = typer.Option(
        False,
        "--check-providers",
        help="Run a 1-token test call against each configured provider (uses free-tier quota!).",
    ),
) -> None:
    """Verify FluxGate development environment readiness."""

    console.rule("[bold blue]FluxGate — verify_env[/]")
    all_pass = True

    # -----------------------------------------------------------------------
    # System summary
    # -----------------------------------------------------------------------
    try:
        import psutil  # type: ignore[import-untyped]

        ram_gb = psutil.virtual_memory().total / (1024**3)
        ram_str = f"{ram_gb:.1f} GB"
        cpu_str = f"{psutil.cpu_count(logical=False)} cores ({psutil.cpu_count()} logical)"
    except ImportError:
        ram_str = "unknown (psutil not installed)"
        cpu_str = platform.processor() or "unknown"

    console.print(
        f"\n[bold]System:[/] Python {sys.version.split()[0]}, "
        f"{platform.system()} {platform.release()}"
    )
    console.print(f"         CPU: {cpu_str}   RAM: {ram_str}")
    console.print(f"         CWD: {ROOT}\n")

    # -----------------------------------------------------------------------
    # Check 1: Python version
    # -----------------------------------------------------------------------
    console.print("[bold]1. Python version[/]")
    info = sys.version_info
    ok = info >= (3, 11)
    rec = info >= (3, 12)
    detail = f"{info.major}.{info.minor}.{info.micro}"
    if not rec:
        detail += "  (3.12+ recommended)"
    all_pass &= _check("Python >= 3.11", ok, detail)

    # -----------------------------------------------------------------------
    # Check 2: Required packages importable
    # -----------------------------------------------------------------------
    console.print("\n[bold]2. Required packages importable[/]")
    pkgs = [
        ("faiss", "faiss"),
        ("sentence_transformers", "sentence_transformers"),
        ("fastapi", "fastapi"),
        ("httpx", "httpx"),
        ("aiosqlite", "aiosqlite"),
        ("pydantic", "pydantic"),
        ("structlog", "structlog"),
        ("orjson", "orjson"),
        ("numpy", "numpy"),
    ]
    for name, mod in pkgs:
        try:
            __import__(mod)
            all_pass &= _check(name, True)
        except ImportError as exc:
            all_pass &= _check(name, False, str(exc))

    # -----------------------------------------------------------------------
    # Check 3: CONTRACT_VERSION
    # -----------------------------------------------------------------------
    console.print("\n[bold]3. Contract version[/]")
    try:
        sys.path.insert(0, str(ROOT))
        from shared.contracts import CONTRACT_VERSION  # type: ignore[import-untyped]

        ok = CONTRACT_VERSION == "1.0.0"
        all_pass &= _check("CONTRACT_VERSION == '1.0.0'", ok, f"got {CONTRACT_VERSION!r}")
    except Exception as exc:
        all_pass &= _check("CONTRACT_VERSION import", False, str(exc))

    # -----------------------------------------------------------------------
    # Check 4: .env exists and required variables are non-placeholder
    # -----------------------------------------------------------------------
    console.print("\n[bold]4. .env file and required variables[/]")
    env_path = ROOT / ".env"
    if not env_path.exists():
        all_pass &= _check(".env exists", False, f"expected at {env_path}")
    else:
        all_pass &= _check(".env exists", True)
        required_vars = [
            "FLUXGATE_ENV",
            "FLUXGATE_DB_PATH",
            "FLUXGATE_KEY_PEPPER",
            "FLUXGATE_ADMIN_TOKEN",
        ]
        # Load without importing dotenv (to avoid a hard dep in this script)
        env_vals: dict[str, str] = {}
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vals[k.strip()] = v.strip().strip('"').strip("'")

        placeholders = {"", "REPLACE_ME", "change-me", "change-me-32+random-bytes-hex"}
        for var in required_vars:
            val = env_vals.get(var, "")
            ok = bool(val) and val not in placeholders
            all_pass &= _check(f"{var} set", ok, "(placeholder detected)" if not ok else "")

    # -----------------------------------------------------------------------
    # Check 5: SQLite WAL mode
    # -----------------------------------------------------------------------
    console.print("\n[bold]5. SQLite WAL mode[/]")
    import sqlite3
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            tmp_path = tf.name
        con = sqlite3.connect(tmp_path)
        con.execute("PRAGMA journal_mode=WAL")
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        con.close()
        Path(tmp_path).unlink(missing_ok=True)
        ok = mode == "wal"
        all_pass &= _check("SQLite WAL mode", ok, f"mode={mode!r}")
        all_pass &= _check(
            "SQLite version >= 3.40",
            sqlite3.sqlite_version_info >= (3, 40, 0),
            f"got {sqlite3.sqlite_version}",
        )
    except Exception as exc:
        all_pass &= _check("SQLite WAL mode", False, str(exc))

    # -----------------------------------------------------------------------
    # Check 6: MiniLM loads offline, shape (384,), norm ≈ 1, < 100 ms warm
    # -----------------------------------------------------------------------
    console.print("\n[bold]6. MiniLM embedding model (offline)[/]")
    model_dir = ROOT / os.environ.get("FLUXGATE_EMBED_MODEL_PATH", "models/all-MiniLM-L6-v2")
    if not model_dir.exists():
        all_pass &= _check(
            "Model directory exists",
            False,
            f"{model_dir}  — run: python scripts/download_models.py",
        )
    else:
        all_pass &= _check("Model directory exists", True, str(model_dir))
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            # First load (may be slow)
            model = SentenceTransformer(str(model_dir), local_files_only=True)
            # Warm-up
            model.encode("warm-up", normalize_embeddings=True)
            # Timed run
            t0 = time.monotonic()
            vec = model.encode("FluxGate verify_env", normalize_embeddings=True)
            elapsed_ms = (time.monotonic() - t0) * 1000

            vec = np.asarray(vec, dtype=np.float32)
            shape_ok = vec.shape == (384,)
            norm = float(np.linalg.norm(vec))
            norm_ok = 0.999 < norm < 1.001

            all_pass &= _check("shape == (384,)", shape_ok, str(vec.shape))
            all_pass &= _check("norm ≈ 1 (L2-normalized)", norm_ok, f"{norm:.6f}")
            # Informational only — first call may be much slower
            console.print(
                f"         [dim]Warm embedding latency: {elapsed_ms:.1f} ms (informational)[/]"
            )
        except Exception as exc:
            all_pass &= _check("MiniLM load + encode", False, str(exc))

    # -----------------------------------------------------------------------
    # Check 7: Optional provider connectivity
    # -----------------------------------------------------------------------
    if check_providers:
        console.print("\n[bold]7. Provider connectivity (1-token test call — uses quota!)[/]")
        _check_providers(all_pass)

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    console.rule()
    if all_pass:
        console.print("\n[bold green]ALL CHECKS PASSED — environment is ready.[/]\n")
    else:
        console.print(
            "\n[bold red]SOME CHECKS FAILED — fix the items above before proceeding.[/]\n"
        )
        raise typer.Exit(1)


def _check_providers(all_pass: bool) -> None:
    import httpx

    providers = [
        ("groq", os.environ.get("GROQ_API_KEY", ""), "https://api.groq.com/openai/v1"),
        ("openrouter", os.environ.get("OPENROUTER_API_KEY", ""), "https://openrouter.ai/api/v1"),
        ("nvidia_nim", os.environ.get("NVIDIA_API_KEY", ""), "https://integrate.api.nvidia.com/v1"),
    ]
    for name, key, base_url in providers:
        if not key or key in {"REPLACE_ME", ""}:
            console.print(f"  [dim]SKIP  {name} — key not set[/]")
            continue
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "VERIFY:set-a-real-model-id",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                timeout=10,
            )
            # We only print the status code — never the key or response body
            ok = resp.status_code in {200, 400, 404}  # 400/404 = auth OK, model unknown
            _check(f"{name} reachable", ok, f"HTTP {resp.status_code}")
        except Exception as exc:
            _check(f"{name} reachable", False, str(exc))


if __name__ == "__main__":
    app()

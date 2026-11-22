"""Create a development virtual key (fgx-…) for local testing.

Usage::

    python scripts/create_dev_key.py [--tenant default] [--name "dev key"]

Behaviour (GIT_AND_COLLAB_WORKFLOW.md §10, TRD §B3):
  - Mints a raw key: fgx- + secrets.token_urlsafe(32) (≈ 43 chars).
  - Derives key_hash = HMAC-SHA256(FLUXGATE_KEY_PEPPER, raw_key).
  - Inserts a row into virtual_keys (status=active, default limits).
  - Prints the raw key **once** to stdout and exits.
  - The raw key is NEVER stored, never logged, never written to any file.
  - Requires FLUXGATE_DB_PATH and FLUXGATE_KEY_PEPPER set in .env or environment.

WARNING: This script does NOT start the full gateway (no ASGI app required).
It operates directly on the SQLite DB via aiosqlite.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(
    name="create_dev_key",
    help="Mint a fgx- virtual key for local development (printed once; never stored raw).",
    add_completion=False,
)
console = Console()

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    """Load .env from the repo root if it exists (minimal loader, no dotenv dep)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


@app.command()
def main(
    tenant: str = typer.Option("default", "--tenant", help="Tenant ID to associate the key with."),
    name: str = typer.Option("dev-key", "--name", help="Human-readable label for the key."),
    rpm_limit: int = typer.Option(60, "--rpm", help="Requests per minute limit."),
    burst: int = typer.Option(10, "--burst", help="Token bucket burst capacity."),
) -> None:
    """Mint and store a development fgx- virtual key."""
    _load_env()
    asyncio.run(_create_key(tenant=tenant, name=name, rpm_limit=rpm_limit, burst=burst))


async def _create_key(*, tenant: str, name: str, rpm_limit: int, burst: int) -> None:
    import time

    try:
        import aiosqlite
    except ImportError:
        console.print("[bold red]ERROR:[/] aiosqlite not installed. Run: uv sync --extra dev")
        raise typer.Exit(1) from None

    try:
        from python_ulid import ULID  # type: ignore[import-untyped]

        def new_ulid() -> str:
            return str(ULID())
    except ImportError:
        import uuid

        def new_ulid() -> str:  # type: ignore[misc]
            return str(uuid.uuid4()).replace("-", "").upper()[:26]

    db_path = os.environ.get("FLUXGATE_DB_PATH", "./data/fluxgate.db")
    pepper = os.environ.get("FLUXGATE_KEY_PEPPER", "")

    if not pepper or pepper in {"change-me", "change-me-32+random-bytes-hex"}:
        console.print(
            "[bold red]ERROR:[/] FLUXGATE_KEY_PEPPER is not set or is a placeholder.\n"
            '       Generate one: python -c "import secrets; print(secrets.token_hex(32))"\n'
            "       Then add it to .env: FLUXGATE_KEY_PEPPER=<value>"
        )
        raise typer.Exit(1)

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    if not db_file.exists():
        console.print(
            f"[bold red]ERROR:[/] Database not found at {db_file.resolve()}.\n"
            "       Run migrations first: make db-migrate"
        )
        raise typer.Exit(1)

    # Mint key
    raw_key = "fgx-" + secrets.token_urlsafe(32)
    key_prefix = raw_key[:12]  # "fgx-" + 8 chars

    # Derive hash (never store raw key)
    key_hash = hmac.new(
        pepper.encode(),
        raw_key.encode(),
        hashlib.sha256,
    ).hexdigest()

    key_id = new_ulid()
    now_ms = int(time.time() * 1000)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        # Verify tenant exists
        row = await (await db.execute("SELECT id FROM tenants WHERE id=?", (tenant,))).fetchone()
        if row is None:
            console.print(f"[bold red]ERROR:[/] Tenant {tenant!r} does not exist in the database.")
            raise typer.Exit(1)

        await db.execute(
            """
            INSERT INTO virtual_keys
              (id, tenant_id, name, key_prefix, key_hash, status,
               rpm_limit, burst, created_at, created_by)
            VALUES (?,?,?,?,?,'active',?,?,?,'create_dev_key.py')
            """,
            (key_id, tenant, name, key_prefix, key_hash, rpm_limit, burst, now_ms),
        )
        await db.commit()

    console.print("\n[bold green]Virtual key created[/]")
    console.print(f"  Key ID     : {key_id}")
    console.print(f"  Prefix     : {key_prefix}")
    console.print(f"  Tenant     : {tenant}")
    console.print(f"  RPM limit  : {rpm_limit}")
    console.print()
    console.print("[bold yellow]⚠  Copy this key NOW — it will not be shown again:[/]")
    console.print()
    # Print to stdout (not rich) so it can be piped/captured cleanly
    print(raw_key, flush=True)
    console.print()
    console.print("[dim]Set as: OPENAI_API_KEY=<key>  (with base_url=http://localhost:8000/v1)[/]")
    # Overwrite raw_key in memory (best-effort)
    raw_key = "CLEARED"


if __name__ == "__main__":
    app()

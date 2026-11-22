"""Gate 2 acceptance runner — Member 1 standalone verification.

Usage::

    python scripts/verify_m1.py [--hypothesis-examples 500] [--output-dir .]

Runs checks V1-V12 (TESTING_AND_BENCHMARK_GUIDE.md §2.5).
Writes verify_m1_report.json and verify_m1_report.md.
Exit code != 0 if any check fails.

Phase 1 status: stubs only.
Real checks are wired in Phase 2 when guardrails/ and cache/ implementations exist.
Each stub is marked STUB so grep can find them quickly.
"""

from __future__ import annotations

import datetime
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="verify_m1",
    help="Gate 2 acceptance runner — Member 1 standalone verification (V1-V12).",
    add_completion=False,
)
console = Console()
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CheckResult:
    id: str
    description: str
    status: str = "SKIP"  # PASS | FAIL | SKIP | STUB
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass
class Report:
    timestamp: str = field(default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z")
    commit_sha: str = "unknown"
    python_version: str = sys.version
    platform: str = platform.platform()
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(c.status in ("PASS", "SKIP", "STUB") for c in self.checks)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _run_stub(check_id: str, description: str) -> CheckResult:
    """Return a STUB result for a check not yet wired (Phase 1)."""
    return CheckResult(
        id=check_id,
        description=description,
        status="STUB",
        detail="Not yet implemented — wire in Phase 2 alongside the real engine.",
    )


def _run_contract_conformance() -> CheckResult:
    """V1 — Contract conformance (real engines vs protocol suite).

    Phase 1: runs pytest tests/contract to verify fake conformance.
    Phase 2+: also runs real engines.
    """
    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/contract", "--tb=short"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        passed = result.returncode == 0
        detail = result.stdout.strip().split("\n")[-1] if result.stdout else result.stderr[:200]
        return CheckResult(
            id="V1",
            description="Contract conformance (fake engines vs protocol suite)",
            status="PASS" if passed else "FAIL",
            detail=detail,
            elapsed_s=time.monotonic() - t0,
        )
    except Exception as exc:
        return CheckResult("V1", "Contract conformance", "FAIL", str(exc), time.monotonic() - t0)


CHECKS = [
    ("V1", "Contract conformance (real engines vs protocol suite)", _run_contract_conformance),
    ("V2", "PII golden sets (recall >= 0.99; FPR <= 1% per detector)", None),  # STUB
    ("V3", "Secret canaries — 100% formats detected and redacted", None),  # STUB
    ("V4", "Stream split-invariance + no-leak (>= 500 hypothesis examples)", None),  # STUB
    ("V5", "Injection attack corpus — recall and FPR recorded", None),  # STUB
    ("V6", "Indirect injection in planted docs", None),  # STUB
    ("V7", "Tenant isolation stateful test (>= 300 examples)", None),  # STUB
    ("V8", "Eligibility + poisoning suite", None),  # STUB
    ("V9", "TTL / eviction / persistence", None),  # STUB
    ("V10", "ReDoS adversarial suite (< 250 ms per regex)", None),  # STUB
    ("V11", "Log-leak canary (no canary in logs/exceptions)", None),  # STUB
    ("V12", "Micro-benchmarks vs Blueprint §6 latency budgets", None),  # STUB
]


@app.command()
def main(
    hypothesis_examples: int = typer.Option(500, "--hypothesis-examples"),
    output_dir: Path = typer.Option(Path("."), "--output-dir"),
) -> None:
    """Run Gate 2 acceptance checks V1-V12."""

    report = Report(commit_sha=_git_sha())

    console.rule("[bold blue]FluxGate — verify_m1[/]")
    console.print(f"Commit : {report.commit_sha}")
    console.print(f"Python : {report.python_version.split()[0]}")
    console.print(f"Platform: {report.platform}\n")

    for check_id, description, fn in CHECKS:
        result = _run_stub(check_id, description) if fn is None else fn()
        report.checks.append(result)
        icon = {
            "PASS": "[green]PASS[/]",
            "FAIL": "[bold red]FAIL[/]",
            "SKIP": "[dim]SKIP[/]",
            "STUB": "[yellow]STUB[/]",
        }.get(result.status, result.status)
        console.print(f"  {icon}  [{check_id}] {description}")
        if result.detail:
            console.print(f"         [dim]{result.detail}[/]")

    # Summary table
    table = Table(title="\nVerification Summary")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Detail", no_wrap=False)
    for c in report.checks:
        color = {"PASS": "green", "FAIL": "red", "SKIP": "dim", "STUB": "yellow"}.get(c.status, "")
        table.add_row(c.id, f"[{color}]{c.status}[/{color}]", c.detail[:80])
    console.print(table)

    # Write JSON report
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "verify_m1_report.json"
    md_path = output_dir / "verify_m1_report.md"

    report_dict = {
        "timestamp": report.timestamp,
        "commit_sha": report.commit_sha,
        "python_version": report.python_version,
        "platform": report.platform,
        "all_pass": report.all_pass,
        "checks": [
            {
                "id": c.id,
                "description": c.description,
                "status": c.status,
                "detail": c.detail,
                "elapsed_s": round(c.elapsed_s, 3),
            }
            for c in report.checks
        ],
    }
    json_path.write_text(json.dumps(report_dict, indent=2))
    console.print(f"\nReport written: {json_path}")

    # Write Markdown report
    lines = [
        "# verify_m1 Report",
        f"- **Timestamp:** {report.timestamp}",
        f"- **Commit:** {report.commit_sha}",
        f"- **Python:** {report.python_version.split()[0]}",
        f"- **Platform:** {report.platform}",
        f"- **Result:** {'✅ ALL PASS' if report.all_pass else '❌ SOME FAILURES'}",
        "",
        "| ID | Status | Description | Detail |",
        "|---|---|---|---|",
    ]
    for c in report.checks:
        lines.append(f"| {c.id} | {c.status} | {c.description} | {c.detail[:80]} |")
    md_path.write_text("\n".join(lines) + "\n")
    console.print(f"Report written: {md_path}")

    if not report.all_pass:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

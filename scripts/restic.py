#!/home/alpha/.local/bin/uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pendulum>=3.0",
#     "opentelemetry-api>=1.20",
#     "opentelemetry-sdk>=1.20",
#     "opentelemetry-exporter-otlp-proto-http>=1.20",
# ]
# ///
"""Restic backup script - backs up Pondside to Backblaze B2.

A standalone script that runs a Restic backup and handles retention.
Run it any time to back up Pondside. Pulse schedules it every 10 minutes,
but you can also run it manually after big changes.

Usage:
    ./restic.py              # Run backup with retention
    ./restic.py --no-prune   # Backup only, skip retention pruning
    ./restic.py --dry-run    # Show what would be backed up
"""

import argparse
import os
import shutil
import subprocess
import sys

import pendulum
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode


# === Config ===
RESTIC_REPO = os.getenv(
    "RESTIC_REPOSITORY", "s3:s3.us-west-000.backblazeb2.com/alpha-pondside-backup"
)
BACKUP_PATH = "/Pondside"

# Find restic binary - check common locations
RESTIC_BIN = shutil.which("restic") or "/usr/bin/restic"

# Exclusions - reconstructible, generated, or ephemeral files
EXCLUDES = [
    ".git/objects",
    "node_modules",
    "__pycache__",
    ".venv",
    "*.pyc",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    "*.egg-info",
    # Redis data - ephemeral cache, runs as different user, rebuilds itself
    "Basement/Redis/data",
    # Mitmproxy captures - large and transient
    "Basement/Eavesdrop/data/flows.mitm",
]

# Retention policy
RETENTION = {
    "keep-hourly": "24",
    "keep-daily": "7",
    "keep-weekly": "4",
    "keep-monthly": "6",
}


# === OTel Setup ===
def init_otel() -> trace.Tracer | None:
    """Initialize OTel if endpoint is configured. Returns None if not."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None

    resource = Resource.create({SERVICE_NAME: "restic-backup"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    print(f"OTel enabled: {endpoint}")
    return trace.get_tracer("restic-backup")


# === Restic Commands ===
def run_restic(*args: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    """Run a restic command with the configured repository."""
    cmd = [RESTIC_BIN, "-r", RESTIC_REPO, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def backup(dry_run: bool = False, span: trace.Span | None = None) -> bool:
    """Run the backup. Returns True on success."""
    backup_args = ["backup", BACKUP_PATH]

    for pattern in EXCLUDES:
        backup_args.extend(["--exclude", pattern])

    if dry_run:
        backup_args.append("--dry-run")

    print(f"Starting backup of {BACKUP_PATH}")
    if dry_run:
        print("(dry run - no changes will be made)")

    result = run_restic(*backup_args)

    if result.returncode != 0:
        print(f"Backup failed!")
        print(f"stderr: {result.stderr[-1000:] if result.stderr else 'none'}")
        if span:
            span.set_attribute("backup.status", "failed")
            span.set_attribute("backup.error", result.stderr[:500] if result.stderr else "unknown")
        return False

    # Parse output for stats
    print("Backup complete")
    if result.stdout:
        # Show the summary lines
        for line in result.stdout.split('\n'):
            if any(x in line.lower() for x in ['added', 'processed', 'snapshot']):
                print(f"  {line}")

    if span:
        span.set_attribute("backup.status", "success")

    return True


def prune(span: trace.Span | None = None) -> bool:
    """Apply retention policy. Returns True on success."""
    print("Applying retention policy...")

    prune_args = ["forget"]
    for key, value in RETENTION.items():
        prune_args.extend([f"--{key}", value])
    prune_args.append("--prune")

    result = run_restic(*prune_args)

    if result.returncode != 0:
        print(f"Prune failed!")
        print(f"stderr: {result.stderr[-500:] if result.stderr else 'none'}")
        if span:
            span.set_attribute("prune.status", "failed")
        return False

    print("Retention policy applied")
    if span:
        span.set_attribute("prune.status", "success")

    return True


# === Main ===
def main():
    parser = argparse.ArgumentParser(
        description="Restic backup script for Pondside",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ./restic.py              # Full backup with retention
    ./restic.py --no-prune   # Backup only, skip pruning
    ./restic.py --dry-run    # Show what would happen
        """
    )
    parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Skip retention pruning after backup"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be backed up without making changes"
    )
    args = parser.parse_args()

    # Check restic is available
    if not os.path.exists(RESTIC_BIN):
        print(f"Error: restic not found at {RESTIC_BIN}")
        sys.exit(1)

    # Check required env vars
    required_vars = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "RESTIC_PASSWORD"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    now = pendulum.now("America/Los_Angeles")
    print("=" * 60)
    print(f"Restic Backup - {now.format('ddd MMM D YYYY, h:mm A')}")
    print("=" * 60)
    print(f"Repository: {RESTIC_REPO}")
    print(f"Backup path: {BACKUP_PATH}")
    print(f"Restic binary: {RESTIC_BIN}")
    print()

    # Init OTel
    tracer = init_otel()

    # Context manager for span
    from contextlib import nullcontext
    span_ctx = tracer.start_as_current_span("restic.backup") if tracer else nullcontext()

    with span_ctx as span:
        if span:
            span.set_attribute("backup.path", BACKUP_PATH)
            span.set_attribute("backup.repository", RESTIC_REPO)
            span.set_attribute("backup.dry_run", args.dry_run)

        # Run backup
        success = backup(dry_run=args.dry_run, span=span)

        if not success:
            if span:
                span.set_status(Status(StatusCode.ERROR, "Backup failed"))
            sys.exit(1)

        # Run prune unless skipped or dry run
        if not args.no_prune and not args.dry_run:
            prune_success = prune(span=span)
            if not prune_success:
                # Prune failure is warning, not fatal
                print("Warning: Prune failed, but backup succeeded")

        if span:
            span.set_status(Status(StatusCode.OK))

    # Flush traces
    if tracer:
        trace.get_tracer_provider().force_flush(timeout_millis=5000)

    print()
    print("Done!")


if __name__ == "__main__":
    main()

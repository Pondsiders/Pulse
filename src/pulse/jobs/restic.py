"""Restic backup job - hourly backup of Pondside to Backblaze B2."""

import os
import subprocess

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

# Restic configuration
RESTIC_REPO = os.getenv(
    "RESTIC_REPOSITORY", "s3:s3.us-west-000.backblazeb2.com/alpha-pondside-backup"
)
BACKUP_PATH = "/Pondside"

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

log = get_logger()


def run_restic(*args: str) -> subprocess.CompletedProcess:
    """Run a restic command with the configured repository."""
    cmd = ["restic", "-r", RESTIC_REPO, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600)


@scheduler.scheduled_job("cron", minute="*/10", id="backup_pondside")
def backup_pondside():
    """Backup Pondside to Backblaze B2 via Restic. Runs every 10 minutes."""
    tracer = get_tracer()
    with tracer.start_as_current_span("pulse.job.restic") as s:
        s.set_attribute("schedule", "every-10-min")
        try:
            # Build backup command with exclusions
            backup_args = ["backup", BACKUP_PATH]
            for pattern in EXCLUDES:
                backup_args.extend(["--exclude", pattern])

            log.info(f"Starting backup of {BACKUP_PATH}")
            result = run_restic(*backup_args)

            if result.returncode != 0:
                s.set_attribute("status", "failed")
                s.set_attribute("error", result.stderr[:1000] if result.stderr else "")
                log.error(f"Backup failed: {result.stderr[-500:] if result.stderr else 'unknown error'}")
                return  # Don't prune if backup failed

            log.info("Backup complete")

            # Prune old snapshots per retention policy
            log.info("Pruning old snapshots")
            prune_result = run_restic(
                "forget",
                "--keep-hourly",
                "24",
                "--keep-daily",
                "7",
                "--keep-weekly",
                "4",
                "--keep-monthly",
                "6",
                "--prune",
            )

            if prune_result.returncode != 0:
                log.warning(f"Prune failed (backup succeeded): {prune_result.stderr[-500:] if prune_result.stderr else ''}")
            else:
                log.info("Prune complete")

            s.set_attribute("status", "success")

        except subprocess.TimeoutExpired:
            s.set_attribute("status", "timeout")
            log.error("Backup timed out after 1 hour")

        except Exception as e:
            s.set_attribute("status", "error")
            s.set_attribute("error", str(e))
            log.error(f"Unexpected error during backup: {e}")

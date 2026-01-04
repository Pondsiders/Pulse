"""Restic backup job - hourly backup of Pondside to Backblaze B2."""

import os
import subprocess

import logfire

from pulse.scheduler import scheduler

# Restic configuration
RESTIC_REPO = os.getenv(
    "RESTIC_REPOSITORY", "s3:s3.us-west-000.backblazeb2.com/alpha-pondside-backup"
)
BACKUP_PATH = "/Volumes/Pondside"

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


def run_restic(*args: str) -> subprocess.CompletedProcess:
    """Run a restic command with the configured repository."""
    cmd = ["restic", "-r", RESTIC_REPO, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600)


@scheduler.scheduled_job("cron", minute=0, id="backup_pondside")
def backup_pondside():
    """Hourly backup of Pondside to Backblaze B2 via Restic. Runs at :00 every hour."""
    with logfire.span("pulse.job.restic", schedule="hourly") as span:
        try:
            # Build backup command with exclusions
            backup_args = ["backup", BACKUP_PATH]
            for pattern in EXCLUDES:
                backup_args.extend(["--exclude", pattern])

            logfire.info("Starting backup", path=BACKUP_PATH)
            result = run_restic(*backup_args)

            if result.returncode != 0:
                span.set_attribute("status", "failed")
                span.set_attribute("error", result.stderr)
                logfire.error(
                    "Backup failed",
                    returncode=result.returncode,
                    stderr=result.stderr[-1000:] if result.stderr else None,
                )
                return  # Don't prune if backup failed

            logfire.info(
                "Backup complete",
                stdout_tail=result.stdout[-500:] if result.stdout else None,
            )

            # Prune old snapshots per retention policy
            logfire.info("Pruning old snapshots")
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
                logfire.warn(
                    "Prune failed (backup succeeded)",
                    returncode=prune_result.returncode,
                    stderr=prune_result.stderr[-500:] if prune_result.stderr else None,
                )
            else:
                logfire.info(
                    "Prune complete",
                    stdout_tail=prune_result.stdout[-500:] if prune_result.stdout else None,
                )

            span.set_attribute("status", "success")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            logfire.error("Backup timed out after 1 hour")

        except Exception as e:
            span.set_attribute("status", "error")
            span.set_attribute("error", str(e))
            logfire.error("Unexpected error during backup", error=str(e))

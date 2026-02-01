"""Restic backup job - runs the restic.py script every 10 minutes."""

import subprocess
from pathlib import Path

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

SCRIPT_PATH = Path("/Pondside/Basement/Pulse/scripts/restic.py")

log = get_logger()


@scheduler.scheduled_job("cron", minute="*/10", id="backup_pondside")
def backup_pondside():
    """Backup Pondside to Backblaze B2 via Restic. Runs every 10 minutes."""
    tracer = get_tracer()
    with tracer.start_as_current_span("pulse.job.restic") as s:
        s.set_attribute("schedule", "every-10-min")

        if not SCRIPT_PATH.exists():
            log.error(f"Restic script not found at {SCRIPT_PATH}")
            s.set_attribute("status", "error")
            s.set_attribute("error", "script_not_found")
            return

        try:
            log.info("Starting Restic backup via script")

            # Run the script - it handles everything including OTel
            result = subprocess.run(
                ["uv", "run", "--script", str(SCRIPT_PATH)],
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour max
            )

            if result.returncode != 0:
                s.set_attribute("status", "failed")
                s.set_attribute("error", result.stderr[:1000] if result.stderr else "")
                log.error(f"Backup script failed: {result.stderr[-500:] if result.stderr else 'unknown'}")
            else:
                s.set_attribute("status", "success")
                log.info("Backup complete")

        except subprocess.TimeoutExpired:
            s.set_attribute("status", "timeout")
            log.error("Backup timed out after 1 hour")

        except Exception as e:
            s.set_attribute("status", "error")
            s.set_attribute("error", str(e))
            log.error(f"Unexpected error: {e}")

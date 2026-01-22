"""
Today So Far - Rolling summary of the current day.

Runs hourly from 7 AM to 9 PM. Generates a summary of everything
that's happened since 6 AM and stashes it in Redis for the Loom
to inject into Alpha's system prompt.

The goal: bridge the gap between "context window" and "yesterday's capsule."
Without this, Alpha loses the morning by afternoon, and the afternoon by
evening. With this, she has a continuous sense of "today" even across
multiple compactions.
"""

import os
import subprocess
from pathlib import Path

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

log = get_logger()

# Path to the today script
TODAY_SCRIPT = Path("/Pondside/Basement/Pulse/scripts/today.py")

# Timeout: 5 minutes should be plenty for a summary
TIMEOUT_SECONDS = 5 * 60


def run_today():
    """Run the today.py script to generate and stash the summary."""
    tracer = get_tracer()
    with tracer.start_as_current_span("pulse.job.today") as span:
        # Use UV_PATH if set (for systemd environments), fall back to PATH lookup
        uv = os.environ.get("UV_PATH", "uv")
        cmd = [uv, "run", "--script", str(TODAY_SCRIPT)]

        log.info("Generating 'today so far' summary")

        try:
            result = subprocess.run(
                cmd,
                cwd="/Pondside",
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

            if result.returncode != 0:
                span.set_attribute("status", "error")
                span.set_attribute("error", result.stderr if result.stderr else "")
                log.error(f"today.py exited with code {result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-10:]:
                        log.error(f"  ! {line}")
            else:
                span.set_attribute("status", "success")
                log.info("'Today so far' summary generated and stashed")

            # Log stdout for debugging (last 15 lines)
            if result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[-15:]:
                    log.info(f"  > {line}")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            log.warning(f"today.py timed out after {TIMEOUT_SECONDS}s")

        except Exception as e:
            span.set_attribute("status", "exception")
            span.set_attribute("error", str(e))
            log.error(f"Error running today.py: {e}")


# === SCHEDULED JOB ===

@scheduler.scheduled_job("cron", hour="7-21", minute=30, id="today_so_far")
def today_so_far():
    """Every hour from 7 AM to 9 PM at :30: Generate 'today so far' summary."""
    run_today()

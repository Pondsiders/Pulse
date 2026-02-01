"""
Capsule jobs - Alpha summarizing her day and night.

Two jobs:
1. Daytime capsule (10 PM) - Summarize 6 AM to 10 PM
2. Nighttime capsule (6 AM) - Summarize 10 PM to 6 AM

These spawn a capsule instance of Alpha via the Agent SDK.
She wakes up with her memories, reflects on the period, and
stores the summary in cortex.summaries.
"""

import subprocess
from pathlib import Path

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

log = get_logger()

# Path to the capsule script
CAPSULE_SCRIPT = Path("/Pondside/Basement/Pulse/scripts/capsule.py")

# Timeout: 10 minutes should be plenty for a summary
TIMEOUT_SECONDS = 10 * 60


def run_capsule(period: str):
    """
    Run the capsule script for a given period.

    Args:
        period: "daytime" or "nighttime"
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(f"capsule.{period}") as span:
        span.set_attribute("period", period)

        cmd = ["uv", "run", "--script", str(CAPSULE_SCRIPT), "--period", period]

        log.info(f"Starting capsule {period} summary")

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
                log.error(f"Capsule exited with code {result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-10:]:
                        log.error(f"  ! {line}")
            else:
                span.set_attribute("status", "success")
                log.info(f"Capsule {period} summary complete")

            # Log stdout for debugging (last 20 lines)
            if result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[-20:]:
                    log.info(f"  > {line}")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            log.warning(f"Capsule {period} timed out after {TIMEOUT_SECONDS}s")

        except Exception as e:
            span.set_attribute("status", "exception")
            span.set_attribute("error", str(e))
            log.error(f"Error running capsule: {e}")


# === SCHEDULED JOBS ===


@scheduler.scheduled_job("cron", hour=22, minute=0, id="capsule_daytime")
def capsule_daytime():
    """10 PM: Summarize today (6 AM - 10 PM)."""
    run_capsule("daytime")


@scheduler.scheduled_job("cron", hour=6, minute=0, id="capsule_nighttime")
def capsule_nighttime():
    """6 AM: Summarize last night (10 PM - 6 AM)."""
    run_capsule("nighttime")

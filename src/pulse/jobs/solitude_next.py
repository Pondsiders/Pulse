"""
Solitude Next jobs - Alpha's nighttime schedule.

Three jobs:
1. First breath (10 PM) - New session, welcome message
2. Regular breaths (11 PM - 4 AM) - Continue session, simple prompt
3. Last breath (5 AM) - Close out the night

These are DISABLED by default. To enable, change ENABLED to True.
Make sure the old Solitude service is stopped first!
"""

import os
import subprocess
from pathlib import Path

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

log = get_logger()

# === SAFETY SWITCH ===
# Set to True when ready to enable next-gen Solitude
# MAKE SURE OLD SOLITUDE IS DISABLED FIRST
ENABLED = True

# Paths
SOLITUDE_NEXT = Path("/Pondside/Basement/Solitude/src/solitude_next/__init__.py")
FIRST_BREATH = Path("/Pondside/Alpha-Home/infrastructure/first_breath.md")
LAST_BREATH = Path("/Pondside/Alpha-Home/infrastructure/last_breath.md")

# Timeout: 55 minutes (leave 5 min buffer before next hour)
TIMEOUT_SECONDS = 55 * 60


def run_solitude(prompt_file: Path | None = None, breath_type: str = "regular"):
    """
    Run the Solitude Next agent.

    Args:
        prompt_file: Path to special prompt file, or None for regular breath
        breath_type: "first", "regular", or "last" (for logging/tracing)
    """
    if not ENABLED:
        log.info(f"Solitude Next DISABLED - would run {breath_type} breath")
        return

    tracer = get_tracer()
    with tracer.start_as_current_span(f"solitude.{breath_type}") as span:
        span.set_attribute("breath_type", breath_type)

        # Use UV_PATH if set (for systemd environments), fall back to PATH lookup
        uv = os.environ.get("UV_PATH", "uv")
        cmd = [uv, "run", str(SOLITUDE_NEXT), "--breath-type", breath_type]
        if prompt_file:
            cmd.extend(["--prompt", str(prompt_file)])
            span.set_attribute("prompt_file", str(prompt_file))

        log.info(f"Starting Solitude {breath_type} breath")

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
                span.set_attribute("error", result.stderr[:1000] if result.stderr else "")
                log.error(f"Solitude exited with code {result.returncode}")
            else:
                span.set_attribute("status", "success")
                log.info(f"Solitude {breath_type} breath complete")

            # Log stdout for debugging
            if result.stdout:
                # For test flights, log everything. In production, consider [-10:] slice.
                for line in result.stdout.strip().split("\n"):
                    log.info(f"  > {line}")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            log.warning(f"Solitude {breath_type} breath timed out after {TIMEOUT_SECONDS}s")

        except Exception as e:
            span.set_attribute("status", "exception")
            span.set_attribute("error", str(e))
            log.error(f"Error running Solitude: {e}")


# === SCHEDULED JOBS ===
# These only fire if ENABLED is True (checked inside run_solitude)


@scheduler.scheduled_job("cron", hour=22, minute=0, id="solitude_first_breath")
def solitude_first_breath():
    """First breath of the night. 10 PM. New session, welcome message."""
    run_solitude(prompt_file=FIRST_BREATH, breath_type="first")


@scheduler.scheduled_job("cron", hour="23,0,1,2,3,4", minute=0, id="solitude_regular_breath")
def solitude_regular_breath():
    """Regular breaths. 11 PM through 4 AM. Continue session."""
    run_solitude(prompt_file=None, breath_type="regular")


@scheduler.scheduled_job("cron", hour=5, minute=0, id="solitude_last_breath")
def solitude_last_breath():
    """Last breath of the night. 5 AM. Close out the session."""
    run_solitude(prompt_file=LAST_BREATH, breath_type="last")

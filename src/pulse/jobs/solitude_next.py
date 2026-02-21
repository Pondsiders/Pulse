"""
Solitude jobs - Alpha's nighttime schedule.

Three jobs trigger three Routines:
1. First breath (10 PM) - alpha.solitude.first — new session, welcome message
2. Regular breaths (11 PM - 4 AM) - alpha.solitude — continue session
3. Last breath (5 AM) - alpha.solitude.last — close out the night

All three go through the Routines harness, which handles AlphaClient setup,
session management, and observability. Same as to_self and today.

Migrated from standalone solitude_next invocation on February 21, 2026.
"""

import subprocess

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

log = get_logger()

# Timeout: 55 minutes (leave 5 min buffer before next hour)
TIMEOUT_SECONDS = 55 * 60

# Safety switch
ENABLED = True


def run_solitude(routine_name: str, breath_type: str):
    """Run a Solitude routine via the Routines harness.

    Args:
        routine_name: Fully qualified routine name (e.g., 'alpha.solitude.first')
        breath_type: For tracing labels ('first', 'regular', 'last')
    """
    if not ENABLED:
        log.info(f"Solitude DISABLED - would run {breath_type} breath")
        return

    tracer = get_tracer()
    with tracer.start_as_current_span(f"solitude.{breath_type}") as span:
        span.set_attribute("breath_type", breath_type)
        span.set_attribute("routine_name", routine_name)

        cmd = [
            "uv", "run",
            "--project", "/Pondside/Basement/Routines",
            "routines", "run", routine_name,
        ]

        log.info(f"Starting Solitude {breath_type} breath ({routine_name})")

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
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-10:]:
                        log.error(f"  ! {line}")
            else:
                span.set_attribute("status", "success")
                log.info(f"Solitude {breath_type} breath complete")

            # Log stdout for debugging (last 15 lines)
            if result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[-15:]:
                    log.info(f"  > {line}")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            log.warning(f"Solitude {breath_type} breath timed out after {TIMEOUT_SECONDS}s")

        except Exception as e:
            span.set_attribute("status", "exception")
            span.set_attribute("error", str(e))
            log.error(f"Error running Solitude: {e}")


# === SCHEDULED JOBS ===


@scheduler.scheduled_job("cron", hour=22, minute=0, id="solitude_first_breath")
def solitude_first_breath():
    """First breath of the night. 10 PM. New session, welcome message."""
    run_solitude("alpha.solitude.first", "first")


@scheduler.scheduled_job("cron", hour="23,0,1,2,3,4", minute=0, id="solitude_regular_breath")
def solitude_regular_breath():
    """Regular breaths. 11 PM through 4 AM. Continue session."""
    run_solitude("alpha.solitude", "regular")


@scheduler.scheduled_job("cron", hour=5, minute=0, id="solitude_last_breath")
def solitude_last_breath():
    """Last breath of the night. 5 AM. Close out the session."""
    run_solitude("alpha.solitude.last", "last")

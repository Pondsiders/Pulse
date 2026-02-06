"""
To Self job - Alpha's nightly letter to tomorrow-her.

Runs at 9:45 PM, before capsule summaries and Solitude.
Forks from the day's Duckpond session and writes a forward-looking letter
about what she's carrying into tomorrow.
"""

import subprocess

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

log = get_logger()

# Timeout: 5 minutes should be plenty for a letter
TIMEOUT_SECONDS = 5 * 60


def run_to_self():
    """Run the to_self routine via the routines harness."""
    tracer = get_tracer()
    with tracer.start_as_current_span("pulse.job.to_self") as span:
        cmd = ["uv", "run", "--project", "/Pondside/Basement/Routines", "routines", "run", "alpha.to_self"]

        log.info("Starting to_self letter routine")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

            if result.returncode != 0:
                span.set_attribute("status", "error")
                span.set_attribute("error", result.stderr if result.stderr else "")
                log.error(f"to_self exited with code {result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-10:]:
                        log.error(f"  ! {line}")
            else:
                span.set_attribute("status", "success")
                log.info("to_self letter complete")

            # Log stdout for debugging (last 15 lines)
            if result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[-15:]:
                    log.info(f"  > {line}")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            log.warning(f"to_self timed out after {TIMEOUT_SECONDS}s")

        except Exception as e:
            span.set_attribute("status", "exception")
            span.set_attribute("error", str(e))
            log.error(f"Error running to_self: {e}")


# === SCHEDULED JOB ===

@scheduler.scheduled_job("cron", hour=21, minute=45, id="to_self_letter")
def to_self_letter():
    """9:45 PM: Write tomorrow letter before capsule and Solitude."""
    run_to_self()

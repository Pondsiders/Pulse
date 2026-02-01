"""
System prompt parts - gather ambient context for Alpha's system prompt.

Runs hourly at :00, collecting:
- Weather (including sun position)
- Calendar events (Jeffery and Kylee)
- Todoist tasks (Pondside, Alpha, Jeffery)

Results are stashed in Redis with 65-minute TTLs, ready for Eavesdrop's
SystemPromptComposer addon to assemble into the final system prompt.
"""

import subprocess
from pathlib import Path

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler

log = get_logger()

# Path to the system_prompt script
SCRIPT = Path("/Pondside/Basement/Pulse/scripts/system_prompt.py")

# Timeout: 2 minutes should be plenty for API calls
TIMEOUT_SECONDS = 2 * 60


def run_system_prompt():
    """Run the system_prompt script to gather and stash all parts."""
    tracer = get_tracer()
    with tracer.start_as_current_span("pulse.job.system_prompt") as span:
        cmd = ["uv", "run", "--script", str(SCRIPT)]

        log.info("Gathering system prompt parts")

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
                log.error(f"system_prompt.py exited with code {result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-10:]:
                        log.error(f"  ! {line}")
            else:
                span.set_attribute("status", "success")
                log.info("System prompt parts gathered and stashed")

            # Log stdout for debugging (last 15 lines)
            if result.stdout:
                lines = result.stdout.strip().split("\n")
                for line in lines[-15:]:
                    log.info(f"  > {line}")

        except subprocess.TimeoutExpired:
            span.set_attribute("status", "timeout")
            log.warning(f"system_prompt.py timed out after {TIMEOUT_SECONDS}s")

        except Exception as e:
            span.set_attribute("status", "exception")
            span.set_attribute("error", str(e))
            log.error(f"Error running system_prompt.py: {e}")


# === SCHEDULED JOB ===

@scheduler.scheduled_job("cron", minute=0, id="gather_system_prompt")
def gather_system_prompt():
    """Top of every hour: Gather ambient context for system prompt."""
    run_system_prompt()

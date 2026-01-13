"""Pulse entry point - scheduler setup and environment configuration."""

# Initialize environment FIRST, before any other imports that might need secrets
from pulse.env import init_env
init_env()

# Initialize OpenTelemetry (sends traces to Parallax)
from pulse.otel import init_otel, span, get_logger
init_otel()

from pulse.scheduler import scheduler  # noqa: E402
from pulse import jobs  # noqa: E402, F401 - Auto-registers all jobs

log = get_logger()


def main():
    """Start the Pulse scheduler."""
    with span("pulse.startup", jobs=str([job.id for job in scheduler.get_jobs()])):
        log.info("🫀 Pulse starting...")
        log.info(f"   Jobs: {[job.id for job in scheduler.get_jobs()]}")
        log.info(f"   Timezone: {scheduler.timezone}")

    try:
        scheduler.start()  # Blocks forever, handles SIGTERM/SIGINT internally
    except (KeyboardInterrupt, SystemExit):
        with span("pulse.shutdown"):
            log.info("🫀 Pulse stopped")


if __name__ == "__main__":
    main()

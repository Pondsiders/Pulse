"""Pulse entry point - scheduler setup and Logfire configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load secrets first, before any other imports that might need them
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

import logfire  # noqa: E402

logfire.configure(
    service_name="pulse",
    token=os.getenv("LOGFIRE_TOKEN"),
    send_to_logfire="if-token-present",
    console=False,
)

from pulse.scheduler import scheduler  # noqa: E402
from pulse import jobs  # noqa: E402, F401 - Auto-registers all jobs


def main():
    """Start the Pulse scheduler."""
    logfire.info(
        "Pulse starting",
        jobs=[job.id for job in scheduler.get_jobs()],
        timezone=str(scheduler.timezone),
    )
    print("🫀 Pulse starting...")
    print(f"   Jobs: {[job.id for job in scheduler.get_jobs()]}")
    print(f"   Timezone: {scheduler.timezone}")
    print("   Press Ctrl+C to stop")

    try:
        scheduler.start()  # Blocks forever, handles SIGTERM/SIGINT internally
    except (KeyboardInterrupt, SystemExit):
        logfire.info("Pulse shutting down")
        print("\n🫀 Pulse stopped")


if __name__ == "__main__":
    main()

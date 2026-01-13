"""HUD job - gather ambient context for Alpha's peripheral vision.

Every hour, this job collects:
- Weather (Open-Meteo, free, no API key)
- Calendar events for Jeffery and Kylee (Google Calendar ICS)
- Todoist tasks (REST API)

Results are stashed in Redis with 24-hour TTLs, ready for Duckpond
to assemble into the system prompt.

Memory summaries are handled separately by the Capsule system:
- Capsule runs at 10 PM (daytime) and 6 AM (nighttime)
- Summaries are stored in cortex.summaries (Postgres)
- Duckpond pulls them directly from Postgres when building the prompt
"""

import os

import pendulum
import redis

from pulse.otel import get_tracer, get_logger
from pulse.scheduler import scheduler
from .weather import gather_weather
from .calendar import gather_calendar
from .todos import gather_todos

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# HUD keys (24-hour TTL)
HUD_TTL = 24 * 60 * 60  # 24 hours
HUD_KEYS = {
    "updated": "hud:updated",
    "weather": "hud:weather",
    "calendar": "hud:calendar",
    "todos": "hud:todos",
}

log = get_logger()


def get_redis():
    """Get Redis connection."""
    return redis.from_url(REDIS_URL)


@scheduler.scheduled_job("cron", minute=5, id="gather_hud")
def gather_hud():
    """Hourly HUD refresh. Runs at :05 every hour (after any Capsule runs at :00)."""
    tracer = get_tracer()
    with tracer.start_as_current_span("pulse.job.hud") as s:
        s.set_attribute("schedule", "hourly")
        try:
            now = pendulum.now("America/Los_Angeles")
            log.info(f"Gathering HUD data at {now.format('ddd MMM D h:mm A')}")

            # Gather components
            with tracer.start_as_current_span("hud.gather_components"):
                weather = gather_weather()
                calendar = gather_calendar()
                todos = gather_todos()

            # Atomic Redis update
            r = get_redis()
            pipe = r.pipeline()

            timestamp = now.format("ddd MMM D YYYY h:mm A")
            pipe.setex(HUD_KEYS["updated"], HUD_TTL, timestamp)
            pipe.setex(HUD_KEYS["weather"], HUD_TTL, weather or "")
            pipe.setex(HUD_KEYS["calendar"], HUD_TTL, calendar or "")
            pipe.setex(HUD_KEYS["todos"], HUD_TTL, todos or "")

            # Execute atomic update
            pipe.execute()

            log.info(f"HUD data stashed in Redis")
            s.set_attribute("status", "success")

        except Exception as e:
            s.set_attribute("status", "error")
            s.set_attribute("error", str(e))
            log.error(f"Failed to gather HUD data: {e}")
            raise

"""HUD job - gather ambient context for Alpha's peripheral vision.

Every hour, this job collects information Alpha might want to glance at:
- Weather (Open-Meteo, free, no API key)
- Calendar events for Jeffery and Kylee (Google Calendar ICS)
- Todoist tasks (REST API)

The result is stashed in Redis with a 65-minute TTL, ready for Duckpond
to include in the system prompt.
"""

import os
from datetime import datetime

import logfire
import redis

from pulse.scheduler import scheduler
from .weather import gather_weather
from .calendar import gather_calendar
from .todos import gather_todos

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
HUD_KEY = "alpha:hud"
HUD_TTL = 65 * 60  # 65 minutes - slightly longer than the hourly refresh


def get_redis():
    """Get Redis connection."""
    return redis.from_url(REDIS_URL)


def format_hud(data: dict) -> str:
    """Format the HUD data as markdown for inclusion in system prompt."""
    lines = []

    timestamp = data.get("gathered_at", "unknown")
    lines.append(f"*Refreshed {timestamp}*")
    lines.append("")

    # Weather
    if data.get("weather"):
        lines.append(data["weather"])
        lines.append("")

    # Calendar (already has date headers)
    if data.get("calendar"):
        lines.append(data["calendar"])
        lines.append("")

    # Todos
    if data.get("todos"):
        lines.append("**Todos**")
        lines.append(data["todos"])
        lines.append("")

    return "\n".join(lines).strip()


@scheduler.scheduled_job("cron", minute=5, id="gather_hud")
def gather_hud():
    """Hourly HUD refresh. Runs at :05 every hour (after backups)."""
    with logfire.span("pulse.job.hud", schedule="hourly") as span:
        try:
            logfire.info("Gathering HUD data")

            # Gather all the things
            data = {
                "gathered_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "weather": gather_weather(),
                "calendar": gather_calendar(),
                "todos": gather_todos(),
            }

            # Format as markdown
            hud_markdown = format_hud(data)

            # Stash in Redis
            r = get_redis()
            r.setex(HUD_KEY, HUD_TTL, hud_markdown)

            logfire.info("HUD data stashed in Redis",
                        key=HUD_KEY,
                        ttl=HUD_TTL,
                        size=len(hud_markdown))

            span.set_attribute("status", "success")

        except Exception as e:
            span.set_attribute("status", "error")
            span.set_attribute("error", str(e))
            logfire.error("Failed to gather HUD data", error=str(e))

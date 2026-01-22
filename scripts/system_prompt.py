#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pendulum>=3.0",
#     "redis>=5.0",
#     "icalendar>=5.0",
#     "opentelemetry-api>=1.20",
#     "opentelemetry-sdk>=1.20",
#     "opentelemetry-exporter-otlp-proto-http>=1.20",
# ]
# ///
"""System Prompt Parts: Gather ambient context for Alpha's system prompt.

Every hour, this script collects:
- Weather (Open-Meteo, free, no API key) → systemprompt:present:weather
- Sun position (sunrise/sunset times) → included in weather
- Calendar events (Google Calendar ICS) → systemprompt:future:jeffery, systemprompt:future:kylee
- Todoist tasks → systemprompt:future:todos:pondside, :alpha, :jeffery

Results are stashed in Redis with 65-minute TTLs, ready for Eavesdrop's
SystemPromptComposer addon to assemble into the final system prompt.

Usage:
    ./system_prompt.py           # Run all gatherers
    ./system_prompt.py --dry-run # Show what would be stored, don't write to Redis
"""

import argparse
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime

import pendulum
import redis
from icalendar import Calendar
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME


# === Config ===
REDIS_URL = os.getenv("REDIS_URL", "redis://alpha-pi:6379")
TTL_SECONDS = 65 * 60  # 65 minutes - stale data disappears rather than lies

# Timezone (PSO-8601: always local time, America/Los_Angeles)
PACIFIC = "America/Los_Angeles"

# Location for weather
LOCATION = {
    "latitude": 34.1556,
    "longitude": -118.4497,
    "timezone": PACIFIC,
}

# Calendar ICS URLs
CALENDARS = {
    "jeffery": {
        "url": "https://calendar.google.com/calendar/ical/jefferyharrell%40gmail.com/private-4b80d6d8eb2359d54f82d7e1e8be92d8/basic.ics",
        "days_ahead": 14,
    },
    "kylee": {
        "url": "https://calendar.google.com/calendar/ical/kyleepena%40gmail.com/private-3d0dc99ce85c35981f281009b7443b2b/basic.ics",
        "days_ahead": 2,  # Today + tomorrow
    },
}

# Todoist projects to include
TODOIST_PROJECTS = ["Pondside", "Alpha", "Jeffery"]

# WMO Weather codes to emoji and description
WMO_CODES = {
    0: ("☀️", "Clear"), 1: ("🌤️", "Mostly clear"), 2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"), 45: ("🌫️", "Fog"), 48: ("🌫️", "Freezing fog"),
    51: ("🌦️", "Light drizzle"), 53: ("🌦️", "Drizzle"), 55: ("🌧️", "Heavy drizzle"),
    61: ("🌧️", "Light rain"), 63: ("🌧️", "Rain"), 65: ("🌧️", "Heavy rain"),
    71: ("❄️", "Light snow"), 73: ("❄️", "Snow"), 75: ("❄️", "Heavy snow"),
    80: ("🌦️", "Light showers"), 81: ("🌧️", "Showers"), 82: ("⛈️", "Heavy showers"),
    95: ("⛈️", "Thunderstorm"), 96: ("⛈️", "Thunderstorm with hail"),
}


# === OTel Setup ===
def init_otel() -> trace.Tracer | None:
    """Initialize OTel if endpoint is configured."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None

    resource = Resource.create({SERVICE_NAME: "system-prompt"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    print(f"OTel enabled: {endpoint}")
    return trace.get_tracer("system-prompt")


# === PSO-8601 Formatting ===
def pso8601(dt: pendulum.DateTime) -> str:
    """Format datetime in PSO-8601: human-readable local time.

    Example: "Wed Jan 15 2026, 9:00 AM"
    """
    return dt.format("ddd MMM D YYYY, h:mm A")


# === Weather Gathering ===
def gather_weather() -> str | None:
    """Fetch and format weather from Open-Meteo."""
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": LOCATION["latitude"],
        "longitude": LOCATION["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": LOCATION["timezone"],
        "forecast_days": 1,
    })

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"Weather fetch failed: {e}")
        return None

    current = data.get("current", {})
    daily = data.get("daily", {})

    temp = current.get("temperature_2m", 0)
    feels_like = current.get("apparent_temperature", temp)
    humidity = current.get("relative_humidity_2m", 0)
    wind = current.get("wind_speed_10m", 0)
    code = current.get("weather_code", 0)

    emoji, desc = WMO_CODES.get(code, ("❓", "Unknown"))

    high = daily.get("temperature_2m_max", [0])[0]
    low = daily.get("temperature_2m_min", [0])[0]

    # Sunrise/sunset
    sunrise_raw = daily.get("sunrise", [""])[0]
    sunset_raw = daily.get("sunset", [""])[0]
    try:
        sunrise = datetime.fromisoformat(sunrise_raw).strftime("%-I:%M %p")
        sunset = datetime.fromisoformat(sunset_raw).strftime("%-I:%M %p")
    except (ValueError, AttributeError):
        sunrise = "?"
        sunset = "?"

    lines = [
        f"{emoji} **{temp:.0f}°F** {desc} (feels like {feels_like:.0f}°)",
        f"High {high:.0f}° / Low {low:.0f}° · Humidity {humidity}% · Wind {wind:.0f} mph",
        f"☀️ {sunrise} → 🌙 {sunset}",
    ]

    return "\n".join(lines)


# === Calendar Gathering ===
def fetch_calendar(url: str) -> Calendar | None:
    """Fetch and parse an ICS calendar."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return Calendar.from_ical(response.read())
    except Exception as e:
        print(f"Calendar fetch failed: {e}")
        return None


def get_events(cal: Calendar, start_date: pendulum.Date, end_date: pendulum.Date) -> list[dict]:
    """Extract events from a calendar within date range."""
    events = []

    for component in cal.walk():
        if component.name == "VEVENT":
            dtstart = component.get("dtstart")
            if not dtstart:
                continue

            dt = dtstart.dt
            is_all_day = not hasattr(dt, "hour")

            if is_all_day:
                event_date = pendulum.date(dt.year, dt.month, dt.day)
                if start_date <= event_date <= end_date:
                    events.append({
                        "dt": event_date,
                        "summary": str(component.get("summary", "Untitled")),
                        "location": str(component.get("location")) if component.get("location") else None,
                        "all_day": True,
                    })
            else:
                event_dt = pendulum.instance(dt).in_tz(PACIFIC)
                event_date = event_dt.date()
                if start_date <= event_date <= end_date:
                    events.append({
                        "dt": event_dt,
                        "summary": str(component.get("summary", "Untitled")),
                        "location": str(component.get("location")) if component.get("location") else None,
                        "all_day": False,
                    })

    # Sort by date, then all-day before timed, then by time
    def sort_key(e):
        if e["all_day"]:
            return (e["dt"], 0, pendulum.time(0, 0))
        return (e["dt"].date(), 1, e["dt"].time())

    return sorted(events, key=sort_key)


def format_calendar_events(events: list[dict], today: pendulum.Date) -> str:
    """Format events for display, grouped by date."""
    if not events:
        return "No events"

    lines = []
    current_date = None

    for event in events:
        event_date = event["dt"] if event["all_day"] else event["dt"].date()

        if event_date != current_date:
            current_date = event_date
            if event_date == today:
                date_label = "Today"
            elif event_date == today.add(days=1):
                date_label = "Tomorrow"
            else:
                date_label = event_date.format("ddd MMM D")
            lines.append(f"**{date_label}**")

        if event["all_day"]:
            time_str = "(all day)"
        else:
            time_str = event["dt"].format("h:mm A")

        line = f"• {time_str}: {event['summary']}"
        if event["location"]:
            line += f" @ {event['location'][:40]}"
        lines.append(line)

    return "\n".join(lines)


def gather_calendar(name: str) -> str | None:
    """Gather calendar events for a person."""
    config = CALENDARS.get(name)
    if not config:
        return None

    cal = fetch_calendar(config["url"])
    if not cal:
        return None

    now = pendulum.now(PACIFIC)
    today = now.date()
    end_date = today.add(days=config["days_ahead"])

    events = get_events(cal, today, end_date)
    return format_calendar_events(events, today)


# === Todoist Gathering ===
def gather_todos(project_name: str) -> str | None:
    """Gather Todoist tasks for a single project."""
    token = os.environ.get("TODOIST_TOKEN")
    if not token:
        print("TODOIST_TOKEN not set, skipping todos")
        return None

    headers = {"Authorization": f"Bearer {token}"}

    # Get all projects to find the ID
    try:
        req = urllib.request.Request("https://api.todoist.com/rest/v2/projects", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            projects = json.loads(response.read().decode())
    except Exception as e:
        print(f"Todoist projects fetch failed: {e}")
        return None

    project_id = None
    for p in projects:
        if project_name.lower() in p["name"].lower():
            project_id = p["id"]
            break

    if not project_id:
        return "No tasks"

    # Get tasks for this project
    try:
        url = f"https://api.todoist.com/rest/v2/tasks?project_id={project_id}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            tasks = json.loads(response.read().decode())
    except Exception as e:
        print(f"Todoist tasks fetch failed: {e}")
        return None

    if not tasks:
        return "No tasks"

    # Sort by priority (high first)
    tasks.sort(key=lambda t: -t.get("priority", 1))

    # Format
    lines = []
    for task in tasks:
        priority = {4: "[p1]", 3: "[p2]", 2: "[p3]"}.get(task.get("priority", 1), "")
        if priority:
            lines.append(f"• {priority} {task['content']}")
        else:
            lines.append(f"• {task['content']}")

    return "\n".join(lines)


# === Main ===
def main():
    parser = argparse.ArgumentParser(description="Gather system prompt parts")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be stored without writing to Redis")
    args = parser.parse_args()

    tracer = init_otel()
    now = pendulum.now(PACIFIC)

    print("=" * 60)
    print(f"System Prompt Parts: {pso8601(now)}")
    print("=" * 60)
    print()

    # Collect all parts
    parts = {}

    # Present: weather (includes sun position)
    print("Gathering weather...")
    weather = gather_weather()
    if weather:
        parts["systemprompt:present:weather"] = weather
        print(f"  ✓ Weather ({len(weather)} chars)")

    # Future: calendars (separate keys)
    for name in CALENDARS:
        print(f"Gathering {name}'s calendar...")
        cal = gather_calendar(name)
        if cal:
            parts[f"systemprompt:future:{name}"] = cal
            print(f"  ✓ {name.title()}'s calendar ({len(cal)} chars)")

    # Future: todos (separate keys per project)
    for project in TODOIST_PROJECTS:
        print(f"Gathering {project} todos...")
        todos = gather_todos(project)
        if todos:
            parts[f"systemprompt:future:todos:{project.lower()}"] = todos
            print(f"  ✓ {project} todos ({len(todos)} chars)")

    # Timestamp
    parts["systemprompt:updated"] = pso8601(now)

    print()

    if args.dry_run:
        print("=== DRY RUN - Would store: ===")
        for key, value in parts.items():
            print(f"\n[{key}] ({len(value)} chars)")
            print(value)  # Show full content
        return

    # Write to Redis atomically
    print("Writing to Redis...")
    r = redis.from_url(REDIS_URL)
    pipe = r.pipeline()

    for key, value in parts.items():
        pipe.setex(key, TTL_SECONDS, value)

    pipe.execute()
    print(f"  ✓ {len(parts)} keys written with {TTL_SECONDS // 60}-minute TTL")

    print()
    print("=" * 60)

    # Flush OTel
    if tracer:
        trace.get_tracer_provider().force_flush(timeout_millis=5000)
        print("Traces flushed")


if __name__ == "__main__":
    main()

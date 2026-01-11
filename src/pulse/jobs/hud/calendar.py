"""Calendar gathering for HUD - reads Google Calendar ICS feeds.

Uses Pendulum for sane timezone handling. All-day events are compared
as dates (not datetimes) to avoid off-by-one errors from UTC conversion.
"""

import urllib.request

import logfire
import pendulum
from icalendar import Calendar

PACIFIC = "America/Los_Angeles"

# Calendar ICS URLs (Jeffery gets 14 days, Kylee gets today+tomorrow)
CALENDARS = [
    ("Jeffery", "https://calendar.google.com/calendar/ical/jefferyharrell%40gmail.com/private-4b80d6d8eb2359d54f82d7e1e8be92d8/basic.ics", 14),
    ("Kylee", "https://calendar.google.com/calendar/ical/kyleepena%40gmail.com/private-3d0dc99ce85c35981f281009b7443b2b/basic.ics", 1),
]


def fetch_calendar(url: str) -> Calendar | None:
    """Fetch and parse an ICS calendar."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return Calendar.from_ical(response.read())
    except Exception as e:
        logfire.error("Failed to fetch calendar", url=url, error=str(e))
        return None


def get_events(cal: Calendar, start_date: pendulum.Date, end_date: pendulum.Date) -> list[dict]:
    """Extract events from a calendar within date range (inclusive).

    All-day events are compared as dates to avoid timezone hell.
    Timed events are converted to Pacific then compared by date portion.
    """
    events = []

    for component in cal.walk():
        if component.name == "VEVENT":
            dtstart = component.get("dtstart")
            if not dtstart:
                continue

            dt = dtstart.dt
            is_all_day = not hasattr(dt, "hour")

            if is_all_day:
                # All-day event: compare date to date range directly
                # NO timezone conversion—dates are dates
                event_date = pendulum.date(dt.year, dt.month, dt.day)
                if start_date <= event_date <= end_date:
                    events.append({
                        "dt": event_date,
                        "summary": str(component.get("summary", "Untitled")),
                        "location": str(component.get("location")) if component.get("location") else None,
                        "all_day": True,
                        "owner": None,  # Will be set by caller
                    })
            else:
                # Timed event: convert to Pacific, compare date portion
                event_dt = pendulum.instance(dt).in_tz(PACIFIC)
                event_date = event_dt.date()
                if start_date <= event_date <= end_date:
                    events.append({
                        "dt": event_dt,
                        "summary": str(component.get("summary", "Untitled")),
                        "location": str(component.get("location")) if component.get("location") else None,
                        "all_day": False,
                        "owner": None,  # Will be set by caller
                    })

    # Sort: by date, then all-day before timed, then by time
    def sort_key(e):
        if e["all_day"]:
            return (e["dt"], 0, pendulum.time(0, 0))
        else:
            return (e["dt"].date(), 1, e["dt"].time())

    return sorted(events, key=sort_key)


def format_event(event: dict) -> str:
    """Format a single event for HUD display."""
    if event["all_day"]:
        time_str = "(all day)"
    else:
        # Format time: "3:00 PM"
        time_str = event["dt"].format("h:mm A")

    line = f"• {time_str}: {event['summary']}"

    if event["location"]:
        # Truncate long locations
        loc = event["location"][:40]
        line += f" @ {loc}"

    # Add owner tag if not Jeffery (his events are the default)
    if event.get("owner") and event["owner"] != "Jeffery":
        line += f" [{event['owner']}]"

    return line


def gather_calendar() -> str | None:
    """Gather calendar events for HUD display.

    Jeffery's calendar: next 14 days (he rarely adds things)
    Kylee's calendar: today + tomorrow (what's happening now)
    """
    now = pendulum.now(PACIFIC)
    today = now.date()

    all_events = []

    for name, url, days_ahead in CALENDARS:
        cal = fetch_calendar(url)
        if not cal:
            continue

        start_date = today
        end_date = today.add(days=days_ahead)
        events = get_events(cal, start_date, end_date)
        # Tag each event with owner
        for event in events:
            event["owner"] = name
        all_events.extend(events)

    if not all_events:
        return "No events"

    # Sort all events together
    def sort_key(e):
        if e["all_day"]:
            return (e["dt"], 0, pendulum.time(0, 0))
        else:
            return (e["dt"].date(), 1, e["dt"].time())

    all_events.sort(key=sort_key)

    # Group by date for display
    lines = []
    current_date = None

    for event in all_events:
        event_date = event["dt"] if event["all_day"] else event["dt"].date()

        if event_date != current_date:
            current_date = event_date
            # Format date header
            if event_date == today:
                date_label = "Today"
            elif event_date == today.add(days=1):
                date_label = "Tomorrow"
            else:
                date_label = event_date.format("ddd MMM D")
            lines.append(f"**{date_label}**")

        lines.append(format_event(event))

    return "\n".join(lines)

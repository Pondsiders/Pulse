"""Weather gathering for HUD - uses Open-Meteo (free, no API key)."""

import json
import urllib.request
import urllib.parse
from datetime import datetime

from pulse.otel import get_logger

log = get_logger()

# Jeffery's location (Los Angeles area)
LOCATION = {
    "name": "Los Angeles",
    "latitude": 34.1556,
    "longitude": -118.4497,
    "elevation": 210.3,  # meters
    "timezone": "America/Los_Angeles",
}

# WMO Weather codes to emoji and description
WMO_CODES = {
    0: ("☀️", "Clear"),
    1: ("🌤️", "Mostly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"),
    45: ("🌫️", "Fog"),
    48: ("🌫️", "Freezing fog"),
    51: ("🌦️", "Light drizzle"),
    53: ("🌦️", "Drizzle"),
    55: ("🌧️", "Heavy drizzle"),
    56: ("🌨️", "Freezing drizzle"),
    57: ("🌨️", "Heavy freezing drizzle"),
    61: ("🌧️", "Light rain"),
    63: ("🌧️", "Rain"),
    65: ("🌧️", "Heavy rain"),
    66: ("🌨️", "Freezing rain"),
    67: ("🌨️", "Heavy freezing rain"),
    71: ("❄️", "Light snow"),
    73: ("❄️", "Snow"),
    75: ("❄️", "Heavy snow"),
    77: ("🌨️", "Snow grains"),
    80: ("🌦️", "Light showers"),
    81: ("🌧️", "Showers"),
    82: ("⛈️", "Heavy showers"),
    85: ("🌨️", "Light snow showers"),
    86: ("🌨️", "Heavy snow showers"),
    95: ("⛈️", "Thunderstorm"),
    96: ("⛈️", "Thunderstorm with hail"),
    99: ("⛈️", "Severe thunderstorm"),
}


def fetch_weather() -> dict | None:
    """Fetch weather from Open-Meteo API."""
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": LOCATION["latitude"],
        "longitude": LOCATION["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": LOCATION["timezone"],
        "forecast_days": 1,
    })

    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        log.error(f"Failed to fetch weather: {e}")
        return None


def format_weather(data: dict) -> str:
    """Format weather data for HUD display."""
    current = data.get("current", {})
    daily = data.get("daily", {})

    temp = current.get("temperature_2m", 0)
    feels_like = current.get("apparent_temperature", temp)
    humidity = current.get("relative_humidity_2m", 0)
    wind = current.get("wind_speed_10m", 0)
    code = current.get("weather_code", 0)

    emoji, desc = WMO_CODES.get(code, ("❓", "Unknown"))

    # Today's high/low
    high = daily.get("temperature_2m_max", [0])[0]
    low = daily.get("temperature_2m_min", [0])[0]

    # Sunrise/sunset (parse from ISO format, format as time)
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


def gather_weather() -> str | None:
    """Gather and format weather info."""
    data = fetch_weather()
    if not data:
        return None
    return format_weather(data)

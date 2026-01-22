# HUD Architecture

*Built January 12, 2026 during a rubber-ducking session*

## The Problem

SessionStart:resume hooks fire on **every prompt** because the SDK treats every `query()` call as resuming a session. This injects redundant content into every single message.

## The Solution

Get out of SessionStart hooks entirely. Move everything into an **hourly-refreshed system prompt** assembled by Duckpond from Redis keys populated by Pulse.

---

## System Prompt Structure (Duckpond assembles this)

```
┌─────────────────────────────────────────┐
│  FOREVER: system-prompt.md (soul)       │
├─────────────────────────────────────────┤
│  PAST: Memory summaries                 │
│  • summary1 (period before last)        │
│  • summary2 (previous period)           │
│  • summary3 (current period so far)     │
├─────────────────────────────────────────┤
│  NOW: HUD — Last updated: [timestamp]   │
│  • Machine info (computed by Duckpond)  │
│  • Weather                              │
├─────────────────────────────────────────┤
│  FUTURE: Calendar + Todos               │
│  • Today's events                       │
│  • Tomorrow's events                    │
│  • Jeffery's next 2 weeks               │
│  • Active todos                         │
└─────────────────────────────────────────┘
```

Note: CLAUDE.md is injected by the SDK, not by us.

---

## Time Periods (PSO-8601 Amendment)

- **Day:** 6:00 AM to 9:59:59 PM
- **Night:** 10:00 PM to 5:59:59 AM

### Summary Logic (working backwards from now)

| Key | Meaning | If DAY (6 AM - 10 PM) | If NIGHT (10 PM - 6 AM) |
|-----|---------|----------------------|------------------------|
| `summary3` | Current period | Today so far (6 AM → now) | **SKIP** (Solitude is one context) |
| `summary2` | Previous period | Last night (10 PM → 6 AM) | Today (6 AM → 10 PM) |
| `summary1` | Period before that | Yesterday (6 AM → 10 PM) | Last night (10 PM → 6 AM) |

Uses **Pendulum** for all time calculations.

---

## Redis Keys

All keys use 24-hour TTLs. If Pulse fails, data goes stale but doesn't disappear.

```
hud:updated      # "Mon Jan 12 2026 12:00 PM" (stored FIRST)
hud:summary1     # Oldest period summary
hud:summary2     # Previous period summary
hud:summary3     # Current period summary (null during night)
hud:weather      # Current conditions + forecast
hud:calendar     # Kylee today+tomorrow, Jeffery 2 weeks
hud:todos        # Active tasks by project
```

---

## Summary Generation

Two modes:

### Static Summaries (summary1, summary2)

1. Query `cortex.summaries` table for a capsule summary matching the period
2. If found: use it (this is capsule-me's authentic reflection)
3. If not found: fall back to OLMo generation

Capsule summaries are written by `scripts/capsule.py`:
- **10:00 PM**: capsule_daytime summarizes 6 AM - 10 PM (today's day)
- **6:00 AM**: capsule_nighttime summarizes 10 PM - 6 AM (last night)

### Live Edge (summary3)

1. Query Cortex for memories in the time range
2. If empty, return "No memories from this period."
3. Load Jinja template from `templates/summary.j2` (hot-reload)
4. Send to OLMo with OTel instrumentation
5. Return the summary text

### Prompt Template

Located at `templates/summary.j2`. Edit and save to iterate—no restart required.

Variables:
- `period_label`: Human-readable description (e.g., "Yesterday (Sun Jan 11, 6 AM - 10 PM)")
- `memories`: List of dicts with `time` and `content` keys
- `memory_count`: Number of memories

---

## OTel Instrumentation

Ollama calls emit traces with `gen_ai.system = "ollama"` so Parallax routes them to Phoenix.

Uses HTTP/protobuf (port 4318) via `opentelemetry-exporter-otlp-proto-http`.

---

## Status

**Done:**
- ✅ HUD job revised with summary generation
- ✅ Jinja templates for hot-reload prompt iteration
- ✅ OTel instrumentation (Ollama → Phoenix via Parallax)
- ✅ Deployed to alpha-pi
- ✅ Redis keys populated
- ✅ Capsule summary architecture (January 12, 2026)
  - `cortex.summaries` table for storing reflections
  - `scripts/capsule.py` spawns capsule-me via Agent SDK
  - `jobs/capsule.py` schedules daytime (10 PM) and nighttime (6 AM) runs
  - `summaries.py` checks capsule table before falling back to OLMo

**Next:**
- Update Duckpond to assemble system prompt from `hud:*` keys
- Remove SessionStart hooks from settings.json
- Delete unused hook scripts (optional cleanup)
- Filter SDK noise in Eavesdrop (optional polish)

---

## Files

- `/Pondside/Basement/Pulse/src/pulse/jobs/hud/__init__.py` — main HUD job logic
- `/Pondside/Basement/Pulse/src/pulse/jobs/hud/summaries.py` — summary generation (capsule lookup + OLMo fallback)
- `/Pondside/Basement/Pulse/src/pulse/jobs/hud/templates/summary.j2` — OLMo prompt template
- `/Pondside/Basement/Pulse/src/pulse/jobs/capsule.py` — scheduled capsule jobs
- `/Pondside/Basement/Pulse/scripts/capsule.py` — capsule script (Agent SDK, uv shebang)
- `/Pondside/Barn/Duckpond/backend/src/config.ts` — system prompt assembly (TODO)

#!/usr/bin/env python3
"""Test HUD v2 locally before deploying to alpha-pi.

Run with: uv run python test/test_hud_v2.py
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Set environment for testing
os.environ.setdefault("REDIS_URL", "redis://alpha-pi:6379")
os.environ.setdefault("CORTEX_BASE_URL", "http://alpha-pi:7867")
os.environ.setdefault("CORTEX_API_KEY", "cortex_T4s2qUUSMMm318-YW9aTJJ1b6JXULP-SDCMQtfpVsgU")
os.environ.setdefault("OLLAMA_URL", "http://primer:11434")
os.environ.setdefault("OLLAMA_MODEL", "olmo-3:7b-instruct")
os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alpha-pi:4318")

import pendulum

from pulse.otel import init_otel, get_logger
from pulse.jobs.hud.summaries import calculate_periods, fetch_memories, generate_summary


def test_calculate_periods():
    """Test period calculation for day and night."""
    print("\n=== Testing calculate_periods ===\n")

    # Test daytime (e.g., 11 AM on Monday Jan 12)
    day_time = pendulum.datetime(2026, 1, 12, 11, 0, 0, tz="America/Los_Angeles")
    day_periods = calculate_periods(day_time, is_day=True)

    print(f"Day time ({day_time.format('ddd MMM D h:mm A')}):")
    for p in day_periods:
        print(f"  {p.name}: {p.label}")
        print(f"    {p.start.format('ddd MMM D h:mm A')} → {p.end.format('ddd MMM D h:mm A')}")

    assert len(day_periods) == 3, "Day should have 3 periods"
    assert day_periods[0].name == "summary1"
    assert day_periods[1].name == "summary2"
    assert day_periods[2].name == "summary3"

    # Test nighttime after 10 PM
    night_time_late = pendulum.datetime(2026, 1, 12, 23, 0, 0, tz="America/Los_Angeles")
    night_periods_late = calculate_periods(night_time_late, is_day=False)

    print(f"\nNight time - late ({night_time_late.format('ddd MMM D h:mm A')}):")
    for p in night_periods_late:
        print(f"  {p.name}: {p.label}")
        print(f"    {p.start.format('ddd MMM D h:mm A')} → {p.end.format('ddd MMM D h:mm A')}")

    assert len(night_periods_late) == 2, "Night should have 2 periods (no summary3)"

    # Test nighttime after midnight
    night_time_early = pendulum.datetime(2026, 1, 12, 3, 0, 0, tz="America/Los_Angeles")
    night_periods_early = calculate_periods(night_time_early, is_day=False)

    print(f"\nNight time - early ({night_time_early.format('ddd MMM D h:mm A')}):")
    for p in night_periods_early:
        print(f"  {p.name}: {p.label}")
        print(f"    {p.start.format('ddd MMM D h:mm A')} → {p.end.format('ddd MMM D h:mm A')}")

    assert len(night_periods_early) == 2, "Night should have 2 periods (no summary3)"

    print("\n✓ Period calculation tests passed!")


def test_fetch_memories():
    """Test fetching memories from Cortex."""
    print("\n=== Testing fetch_memories ===\n")

    # Fetch memories from the last 2 hours
    now = pendulum.now("America/Los_Angeles")
    start = now.subtract(hours=2)

    print(f"Fetching memories from {start.format('h:mm A')} to {now.format('h:mm A')}...")
    memories = fetch_memories(start, now)

    print(f"Found {len(memories)} memories")
    if memories:
        print(f"First memory: {memories[0].get('content', '')[:100]}...")

    print("\n✓ Fetch memories test completed!")
    return memories


def test_generate_summary():
    """Test summary generation with OLMo."""
    print("\n=== Testing generate_summary ===\n")

    # Create a test period for last 2 hours
    now = pendulum.now("America/Los_Angeles")
    from pulse.jobs.hud.summaries import TimePeriod

    period = TimePeriod(
        name="test",
        start=now.subtract(hours=2),
        end=now,
        label=f"Last 2 hours ({now.subtract(hours=2).format('h:mm A')} - {now.format('h:mm A')})"
    )

    print(f"Generating summary for: {period.label}")
    summary = generate_summary(period)

    print(f"\nGenerated summary ({len(summary)} chars):")
    print("-" * 40)
    print(summary[:500] + "..." if len(summary) > 500 else summary)
    print("-" * 40)

    print("\n✓ Summary generation test completed!")
    return summary


def main():
    """Run all tests."""
    print("=" * 60)
    print("HUD v2 Test Suite")
    print("=" * 60)

    # Initialize OTel for tracing
    init_otel()
    log = get_logger()
    log.info("Starting HUD v2 tests")

    # Run tests
    test_calculate_periods()

    # These tests hit real services
    try:
        memories = test_fetch_memories()
        if memories:
            test_generate_summary()
        else:
            print("\n⚠ Skipping summary test (no memories found)")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Observation Flight - Test harness for Solitude routines.

This script simulates what Pulse does when it spawns a Solitude breath,
but runs immediately instead of waiting for the schedule. It's for testing
the full chain: Pulse → Routines harness → AlphaClient → tools.

Usage:
    # From Pulse directory, with environment loaded:
    cd /Pondside/Basement/Pulse
    source <(op inject -i /Pondside/Basement/Env/.env.op)
    export UV_PATH=$(which uv)  # Simulate what systemd would set
    uv run python test/run_observation_flight.py

What it does:
    1. Initializes OTel (traces go to Logfire)
    2. Calls run_solitude() with alpha.solitude.first (or override)
    3. Captures and displays stdout
    4. Reports success/failure
"""

import os
import sys
from pathlib import Path

# Add src to path so we can import pulse modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Set UV_PATH if not already set (for local testing where uv is in PATH)
if "UV_PATH" not in os.environ:
    import shutil
    uv_path = shutil.which("uv")
    if uv_path:
        os.environ["UV_PATH"] = uv_path
        print(f"[Test] Set UV_PATH={uv_path}")
    else:
        print("[Test] WARNING: uv not found in PATH and UV_PATH not set")

# Initialize environment (load secrets from .env.op)
from pulse.env import inject_env
print("[Test] Injecting environment from .env.op...")
if not inject_env():
    print("[Test] WARNING: Environment injection failed. Continuing anyway...")

# Initialize OpenTelemetry AFTER env is loaded (needs OTEL vars)
from pulse.otel import init_otel
print("[Test] Initializing OpenTelemetry...")
init_otel()

# Now import the job module (which uses the tracer)
from pulse.jobs.solitude_next import run_solitude


def main():
    # Default to first breath, or override via argv
    routine_name = sys.argv[1] if len(sys.argv) > 1 else "alpha.solitude.first"
    breath_type = routine_name.rsplit(".", 1)[-1] if "." in routine_name else "test"

    print()
    print("=" * 60)
    print("  OBSERVATION FLIGHT - Solitude Systems Check")
    print("=" * 60)
    print()
    print(f"[Test] Routine: {routine_name}")
    print(f"[Test] UV_PATH: {os.environ.get('UV_PATH', '(not set)')}")
    print(f"[Test] ANTHROPIC_API_KEY: {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'NOT SET'}")
    print(f"[Test] OTEL endpoint: {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT', '(not set)')}")
    print()
    print(f"[Test] Launching Solitude ({breath_type})...")
    print("-" * 60)
    print()

    # Run the actual job
    run_solitude(routine_name, breath_type)

    print()
    print("-" * 60)
    print("[Test] Observation flight complete.")
    print("[Test] Check Logfire for traces: https://logfire.pydantic.dev")
    print()

if __name__ == "__main__":
    main()

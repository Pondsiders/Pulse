#!/usr/bin/env python3
"""Manually trigger the HUD job for testing."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Load environment
from pulse.env import inject_env
inject_env()

# Initialize OTel
from opentelemetry import trace
from pulse.otel import init_otel, get_logger
init_otel()

# Run the job
from pulse.jobs.hud import gather_hud

log = get_logger()
log.info("Manually triggering HUD job...")

gather_hud()

log.info("Done!")

# Flush OTel spans before exit (BatchSpanProcessor is async)
provider = trace.get_tracer_provider()
if hasattr(provider, 'force_flush'):
    log.info("Flushing OTel spans...")
    provider.force_flush(timeout_millis=5000)
    log.info("Spans flushed.")

"""OpenTelemetry configuration for Pulse.

Sends traces AND logs to Parallax (the OTel collector on alpha-pi:4318).
Uses HTTP/protobuf (not gRPC) to match our standard config.

All Python logging calls automatically become OTel logs via instrumentation,
so log.info("foo") shows up in Logfire alongside traces.
"""

import os
import logging
import sys

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

from opentelemetry.sdk.resources import Resource, SERVICE_NAME

# Module-level tracer and logger
_tracer: trace.Tracer | None = None
_logger: logging.Logger | None = None


def init_otel():
    """Initialize OpenTelemetry with OTLP exporter to Parallax.

    Sets up both trace and log export so everything flows to Logfire.
    """
    global _tracer

    # Get endpoint from environment, default to Parallax on alpha-pi
    base_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alpha-pi:4318")
    traces_endpoint = f"{base_endpoint}/v1/traces"
    logs_endpoint = f"{base_endpoint}/v1/logs"

    resource = Resource.create({
        SERVICE_NAME: "pulse",
    })

    # --- Traces ---
    trace_provider = TracerProvider(resource=resource)
    trace_exporter = OTLPSpanExporter(endpoint=traces_endpoint)
    trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(trace_provider)
    _tracer = trace.get_tracer("pulse")

    # --- Logs ---
    logger_provider = LoggerProvider(resource=resource)
    log_exporter = OTLPLogExporter(endpoint=logs_endpoint)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)

    # Hook Python's logging module to OTel
    # This makes log.info() etc. emit OTel log records
    otel_handler = LoggingHandler(
        level=logging.INFO,
        logger_provider=logger_provider,
    )

    # Add OTel handler to root logger so ALL logs flow to Logfire
    logging.getLogger().addHandler(otel_handler)

    # Quiet down noisy OTel internal loggers
    logging.getLogger("opentelemetry").setLevel(logging.WARNING)

    # Now init our logger and announce
    get_logger().info(f"OTel initialized: traces → {traces_endpoint}, logs → {logs_endpoint}")


def init_logging():
    """Initialize Python logging for Pulse.

    Logs go to BOTH stderr (systemd/journald) AND OTel (Logfire).
    """
    global _logger

    _logger = logging.getLogger("pulse")
    _logger.setLevel(logging.INFO)

    # Don't propagate to root logger (we add OTel handler there separately)
    _logger.propagate = True  # Changed to True so OTel handler catches these

    # Clear any existing handlers
    _logger.handlers.clear()

    # Stderr handler for local visibility (journald)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter('[Pulse] %(levelname)s: %(message)s'))
    _logger.addHandler(stderr_handler)

    return _logger


def get_logger() -> logging.Logger:
    """Get the Pulse logger. Initializes if needed."""
    global _logger
    if _logger is None:
        init_logging()
    return _logger


def get_tracer() -> trace.Tracer:
    """Get the Pulse tracer. Must call init_otel() first."""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer("pulse")
    return _tracer


def span(name: str, **attributes):
    """Create a span with the given name and attributes.

    Usage:
        with span("my.operation", foo="bar"):
            do_stuff()
    """
    tracer = get_tracer()
    s = tracer.start_span(name)
    for k, v in attributes.items():
        s.set_attribute(k, v)
    return trace.use_span(s, end_on_exit=True)

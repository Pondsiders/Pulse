#!/usr/bin/env python3
"""Minimal OLMo trace test.

This script does ONE thing: call OLMo with "Hi how are you" and send
a fully-instrumented trace to Parallax. If this doesn't show up in Phoenix,
we have a fundamental instrumentation problem.

Run with: uv run python test/test_olmo_trace.py
"""

import os
import time
import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode

# Config
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://primer:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "olmo-3:7b-instruct")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://alpha-pi:4318")

def setup_otel() -> trace.Tracer:
    """Set up OTel with explicit configuration."""
    resource = Resource.create({
        SERVICE_NAME: "olmo-test",
    })

    provider = TracerProvider(resource=resource)

    # SimpleSpanProcessor for immediate export (no batching)
    exporter = OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces")
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return trace.get_tracer("olmo-test")


def call_olmo(tracer: trace.Tracer, prompt: str) -> str:
    """Call OLMo with full gen_ai instrumentation."""

    with tracer.start_as_current_span(
        name=f"llm.{OLLAMA_MODEL}",
        kind=trace.SpanKind.CLIENT,
    ) as span:
        # THE CRITICAL ATTRIBUTES for Parallax routing
        span.set_attribute("gen_ai.system", "ollama")
        span.set_attribute("gen_ai.request.model", OLLAMA_MODEL)
        span.set_attribute("gen_ai.operation.name", "generate")

        # OpenInference attributes (what Phoenix expects)
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", OLLAMA_MODEL)
        span.set_attribute("input.value", prompt)

        # Add a marker so we can find this specific test
        span.set_attribute("test.marker", "olmo-trace-test")
        span.set_attribute("test.timestamp", time.time())

        print(f"Span created: trace_id={span.get_span_context().trace_id:032x}")
        print(f"Span created: span_id={span.get_span_context().span_id:016x}")
        print(f"Attributes set: gen_ai.system=ollama")

        try:
            response = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()

            output = result.get("response", "").strip()

            # Record output
            span.set_attribute("output.value", output[:500] if len(output) > 500 else output)
            if "eval_count" in result:
                span.set_attribute("gen_ai.usage.output_tokens", result["eval_count"])
            if "prompt_eval_count" in result:
                span.set_attribute("gen_ai.usage.input_tokens", result["prompt_eval_count"])

            span.set_status(Status(StatusCode.OK))
            print(f"OLMo response: {output[:100]}...")
            return output

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            print(f"Error: {e}")
            raise


def main():
    print("=" * 60)
    print("OLMo Trace Test")
    print("=" * 60)
    print(f"OLLAMA_URL: {OLLAMA_URL}")
    print(f"OLLAMA_MODEL: {OLLAMA_MODEL}")
    print(f"OTEL_ENDPOINT: {OTEL_ENDPOINT}")
    print()

    # Set up OTel
    print("Setting up OpenTelemetry...")
    tracer = setup_otel()
    print("OTel ready.")
    print()

    # Make the call
    print("Calling OLMo...")
    result = call_olmo(tracer, "Hi, how are you? Please respond briefly.")
    print()

    # Force flush
    print("Flushing spans...")
    provider = trace.get_tracer_provider()
    if hasattr(provider, 'force_flush'):
        provider.force_flush()
    print("Done!")
    print()
    print("Check Phoenix for a span named 'llm.olmo-3:7b-instruct' with test.marker='olmo-trace-test'")


if __name__ == "__main__":
    main()

"""OpenTelemetry tracing integration with graceful Arize Phoenix fallback.

Architecture
------------
* We build a standard OTel ``TracerProvider`` and attach a ``BatchSpanProcessor``.
* If Phoenix is enabled and reachable, spans are exported via OTLP/HTTP to
  ``PHOENIX_ENDPOINT`` (default: http://localhost:6006/v1/traces).
* If Phoenix is unreachable or the OTLP package is missing, we fall back to a
  ``ConsoleSpanExporter`` so the application still works without tracing.

Usage
-----
    from llm_observability.services.tracing_service import TracingService

    # Call once at application startup:
    TracingService.initialize(settings)

    # Then get a tracer anywhere:
    tracer = TracingService.get_tracer()
    with tracer.start_as_current_span("my.operation") as span:
        span.set_attribute("key", "value")
        ...
"""

import logging
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

_SERVICE_NAME = "llm-observability"


class TracingService:
    """Singleton that manages the global OTel TracerProvider."""

    _provider: Optional[TracerProvider] = None
    _initialized: bool = False

    # ------------------------------------------------------------------ #
    # Initialisation
    # ------------------------------------------------------------------ #

    @classmethod
    def initialize(cls, settings) -> None:  # type: ignore[no-untyped-def]
        """Set up the TracerProvider.  Must be called once at startup."""
        if cls._initialized:
            return

        from opentelemetry.sdk.resources import Resource

        resource = Resource.create({"service.name": _SERVICE_NAME})
        provider = TracerProvider(resource=resource)

        if settings.phoenix_enabled:
            exporter = cls._build_otlp_exporter(settings.phoenix_endpoint)
        else:
            exporter = ConsoleSpanExporter()
            logger.info("Phoenix tracing disabled — using console span exporter")

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        cls._provider = provider
        cls._initialized = True

    # ------------------------------------------------------------------ #
    # Tracer access
    # ------------------------------------------------------------------ #

    @classmethod
    def get_tracer(cls, name: str = _SERVICE_NAME) -> trace.Tracer:
        """Return a named tracer.

        Auto-initialises with a no-op provider if called before ``initialize()``.
        """
        if not cls._initialized:
            logger.warning(
                "TracingService.get_tracer() called before initialize(); "
                "using no-op provider."
            )
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
            cls._provider = provider
            cls._initialized = True

        return trace.get_tracer(name)

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def _build_otlp_exporter(cls, endpoint: str):
        """Try to create an OTLP/HTTP exporter; fall back to console on failure."""
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
            logger.info("Phoenix OTLP tracing initialised → %s", endpoint)
            return exporter

        except ImportError:
            logger.warning(
                "opentelemetry-exporter-otlp-proto-http not installed; "
                "falling back to console exporter.  "
                "Run: pip install opentelemetry-exporter-otlp-proto-http"
            )
        except Exception as exc:
            logger.warning(
                "Failed to create OTLP exporter (%s); "
                "falling back to console exporter.",
                exc,
            )

        return ConsoleSpanExporter()

import time
import logging
import functools

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource


# 1. Define a Resource — metadata that identifies this service in traces
resource = Resource.create({"service.name": "fastapi-otel-demo"})

# 2. Create a TracerProvider and attach an exporter
#    OTLPSpanExporter reads OTEL_EXPORTER_OTLP_ENDPOINT from the environment when no
#    endpoint is passed — defaults to http://localhost:4317 if the var is not set.
#    This lets docker-compose override it with the tempo/Jaeger service hostname.
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter()
provider.add_span_processor(BatchSpanProcessor(exporter))

# 3. Register the provider globally so trace.get_tracer() uses it everywhere
trace.set_tracer_provider(provider)

# 4. Get a named tracer for this module
tracer = trace.get_tracer(__name__)

# Logging — stdout is captured by Alloy and forwarded to Loki
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="FastAPI + OpenTelemetry Demo")

# 5. Auto-instrument FastAPI — creates a span for every HTTP request automatically
FastAPIInstrumentor.instrument_app(app)


def traced_function(func):
    @functools.wraps(func)
    def tracing_wrapper(*args, **kwargs):
        with tracer.start_as_current_span(func.__name__):
            return func(*args, **kwargs)

    return tracing_wrapper


# @traced_function
@app.get("/")
def root():
    # return {"message": "hello — check Jaeger at http://localhost:16686"}
    return {"message": "hello — check Grafana at http://localhost:3000"}


@app.get("/items/{item_id}")
@traced_function
def get_item(item_id: int):
    # 6. Manual span: wrap a logical unit of work in its own span
    # with tracer.start_as_current_span("fetch-item") as span:
    # 7. Attach structured metadata to the span
    span = trace.get_current_span()
    span.set_attribute("item.id", item_id)

    result = _load_from_db(item_id)

    found = result is not None
    span.set_attribute("item.found", found)
    logger.info("get_item item_id=%s found=%s", item_id, found)
    return result or {"error": "not found"}


def _load_from_db(item_id: int) -> dict | None:
    # 8. Nested span — becomes a child of "fetch-item" automatically
    with tracer.start_as_current_span("db-query") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", f"SELECT * FROM items WHERE id = {item_id}")

        # Simulate DB: only item 42 exists
        if item_id == 42:
            logger.info("db-query hit slow path for item_id=%s, sleeping 1s", item_id)
            time.sleep(1)
            return {"id": 42, "name": "The Answer"}
        return None


@app.get("/error")
def trigger_error():
    with tracer.start_as_current_span("risky-operation") as span:
        try:
            raise ValueError("something went wrong")
        except ValueError as exc:
            # 9. Record exceptions on the span — shows up as an event in Grafana/Jaeger
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))
            logger.error("risky-operation failed: %s", exc)
            return {"error": str(exc)}

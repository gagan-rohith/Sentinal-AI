from fastapi import APIRouter, Response

from observability.metrics import render

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape endpoint.

    Unauthenticated, like most scrape targets: it exposes counts and latencies only, no
    incident data. Restrict it at the network layer in production.
    """
    body, content_type = render()
    return Response(content=body, media_type=content_type)

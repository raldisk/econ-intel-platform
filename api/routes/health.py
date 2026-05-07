"""Health-check route — intentionally thin."""

from fastapi import APIRouter

from api.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Returns ``{"status": "ok"}`` — suitable for load-balancer health checks."""
    return HealthResponse(status="ok")

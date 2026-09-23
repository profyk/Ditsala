from fastapi import APIRouter

from app.api.v1.admin_deps import RevenueServiceDep, require_permission
from app.domain.admin.rbac import Permission
from app.schemas.admin_revenue import RevenueOverviewResponse

router = APIRouter(
    prefix="/admin/revenue",
    tags=["admin-revenue"],
    dependencies=[require_permission(Permission.REVENUE_VIEW)],
)


@router.get("", response_model=RevenueOverviewResponse)
async def get_revenue_overview(service: RevenueServiceDep) -> RevenueOverviewResponse:
    """See `app/domain/admin/revenue.py`'s module docstring for exactly
    what "estimated" means here — a current-state snapshot, not a
    reconciled ledger."""
    overview = await service.get_overview()
    return RevenueOverviewResponse.model_validate(overview)

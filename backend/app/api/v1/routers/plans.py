from fastapi import APIRouter

from app.api.v1.admin_deps import PlanServiceDep
from app.api.v1.deps import CurrentUserDep
from app.schemas.billing import (
    EntitlementResponse,
    MyPlanResponse,
    PlanPriceResponse,
    PublicPlanResponse,
)

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PublicPlanResponse])
async def list_active_plans(_: CurrentUserDep, service: PlanServiceDep) -> list[PublicPlanResponse]:
    """Any authenticated user — backs the Conference Room screen's plan/
    tools comparison with real, admin-configured plans/prices/
    entitlements instead of a hardcoded feature table. Archived plans
    and prices never appear here; that history stays admin-only via
    `/admin/billing/plans/*`."""
    result: list[PublicPlanResponse] = []
    for plan in await service.list_plans():
        if plan.status != "active":
            continue
        prices = [p for p in await service.list_prices(plan.id) if p.status == "active"]
        entitlements = await service.list_entitlements(plan.id)
        result.append(
            PublicPlanResponse(
                id=plan.id,
                code=plan.code,
                product=plan.product,
                name=plan.name,
                prices=[PlanPriceResponse.model_validate(p) for p in prices],
                entitlements=[EntitlementResponse.model_validate(e) for e in entitlements],
            )
        )
    return result


@router.get("/me", response_model=MyPlanResponse)
async def my_plan(user: CurrentUserDep, service: PlanServiceDep) -> MyPlanResponse:
    """Which plan code the caller's own account currently resolves to —
    lets the Conference Room screen highlight "Your plan" among the
    list `list_active_plans` returns."""
    return MyPlanResponse(plan_code=service.resolve_plan_code_for_user(user))

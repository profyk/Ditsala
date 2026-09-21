import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.v1.admin_deps import CurrentAdminDep, PlanServiceDep, require_permission
from app.domain.admin.rbac import Permission
from app.domain.billing.plans import PlanError
from app.schemas.billing import (
    CreatePlanRequest,
    EntitlementResponse,
    PlanPriceResponse,
    PlanResponse,
    SetEntitlementRequest,
    SetPlanPriceRequest,
    SetPlanStatusRequest,
)

router = APIRouter(
    prefix="/admin/billing",
    tags=["admin-billing"],
    dependencies=[require_permission(Permission.BILLING_PLANS_VIEW)],
)


def _as_http_error(exc: PlanError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(service: PlanServiceDep) -> list[PlanResponse]:
    plans = await service.list_plans()
    return [PlanResponse.model_validate(p) for p in plans]


@router.post(
    "/plans",
    response_model=PlanResponse,
    status_code=201,
    dependencies=[require_permission(Permission.BILLING_PLANS_ACTION)],
)
async def create_plan(
    body: CreatePlanRequest, admin: CurrentAdminDep, service: PlanServiceDep
) -> PlanResponse:
    try:
        plan = await service.create_plan(
            admin_id=admin.id, code=body.code, product=body.product, name=body.name
        )
    except PlanError as exc:
        raise _as_http_error(exc) from exc
    return PlanResponse.model_validate(plan)


@router.put(
    "/plans/{plan_id}/status",
    response_model=PlanResponse,
    dependencies=[require_permission(Permission.BILLING_PLANS_ACTION)],
)
async def set_plan_status(
    plan_id: uuid.UUID, body: SetPlanStatusRequest, admin: CurrentAdminDep, service: PlanServiceDep
) -> PlanResponse:
    try:
        plan = await service.set_plan_status(
            admin_id=admin.id, plan_id=plan_id, status=body.status, reason=body.reason
        )
    except PlanError as exc:
        raise _as_http_error(exc) from exc
    return PlanResponse.model_validate(plan)


@router.get("/plans/{plan_id}/prices", response_model=list[PlanPriceResponse])
async def list_plan_prices(plan_id: uuid.UUID, service: PlanServiceDep) -> list[PlanPriceResponse]:
    prices = await service.list_prices(plan_id)
    return [PlanPriceResponse.model_validate(p) for p in prices]


@router.post(
    "/plans/{plan_id}/prices",
    response_model=PlanPriceResponse,
    status_code=201,
    dependencies=[require_permission(Permission.BILLING_PLANS_ACTION)],
)
async def set_plan_price(
    plan_id: uuid.UUID, body: SetPlanPriceRequest, admin: CurrentAdminDep, service: PlanServiceDep
) -> PlanPriceResponse:
    try:
        price = await service.set_price(
            admin_id=admin.id,
            plan_id=plan_id,
            currency=body.currency,
            amount_cents=body.amount_cents,
            billing_interval=body.billing_interval,
            reason=body.reason,
        )
    except PlanError as exc:
        raise _as_http_error(exc) from exc
    return PlanPriceResponse.model_validate(price)


@router.get("/plans/{plan_id}/entitlements", response_model=list[EntitlementResponse])
async def list_plan_entitlements(
    plan_id: uuid.UUID, service: PlanServiceDep
) -> list[EntitlementResponse]:
    entitlements = await service.list_entitlements(plan_id)
    return [EntitlementResponse.model_validate(e) for e in entitlements]


@router.put(
    "/plans/{plan_id}/entitlements",
    response_model=EntitlementResponse,
    dependencies=[require_permission(Permission.BILLING_PLANS_ACTION)],
)
async def set_plan_entitlement(
    plan_id: uuid.UUID, body: SetEntitlementRequest, admin: CurrentAdminDep, service: PlanServiceDep
) -> EntitlementResponse:
    try:
        entitlement = await service.set_entitlement(
            admin_id=admin.id, plan_id=plan_id, key=body.key, value=body.value, reason=body.reason
        )
    except PlanError as exc:
        raise _as_http_error(exc) from exc
    return EntitlementResponse.model_validate(entitlement)

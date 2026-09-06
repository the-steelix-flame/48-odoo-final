"""Fulfillment & stock (screens 7, 8).  Owner: anubhaw0raj."""

from datetime import date, datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import internal_auth, require_role
from apps.common.enums import FulfillmentStatus, QuotationStatus, Role
from apps.common.errors import NotFound
from apps.fulfillment import services
from apps.fulfillment.models import FulfillmentPlan, StockItem, Warehouse
from apps.quotations.models import Quotation

router = Router(auth=internal_auth)

#: Who may LOOK at fulfilment. Stock levels and warehouse allocation are
#: operations data — the brief gives it to Finance/Operations, and a Sales Rep
#: has no decision to make with it. Acting on a plan is narrower still
#: (`Role.FINANCE` on every mutation below), because accepting a split commits
#: stock that every other open deal is competing for.
VIEW_ROLES = (Role.FINANCE, Role.SALES_MANAGER)


class WarehouseOut(Schema):
    id: int
    name: str
    code: str
    shipping_cost_weight: Decimal
    base_shipment_cost: Decimal
    is_active: bool


class StockRowOut(Schema):
    """One row of screen 7's stock table."""

    id: int
    warehouse_id: int
    warehouse_name: str
    product_id: int
    product_name: str
    quantity_on_hand: int
    quantity_reserved: int
    available: int
    needs_replenishment: bool

    @staticmethod
    def resolve_warehouse_name(obj) -> str:
        return obj.warehouse.name

    @staticmethod
    def resolve_product_name(obj) -> str:
        return obj.product.name


class OrderAwaitingOut(Schema):
    """One row of screen 7's 'Orders Awaiting Fulfillment' table."""

    quotation_id: int
    quotation_number: str
    customer_name: str
    status: str
    warehouses: str
    plan_id: int | None = None


class AllocationOut(Schema):
    id: int
    quotation_line_id: int
    line_description: str
    warehouse_id: int
    warehouse_name: str
    quantity: int
    is_backorder: bool
    promised_date: date | None = None
    shipped_at: datetime | None = None

    @staticmethod
    def resolve_line_description(obj) -> str:
        return obj.quotation_line.description

    @staticmethod
    def resolve_warehouse_name(obj) -> str:
        return obj.warehouse.name


class PlanOut(Schema):
    id: int
    quotation_id: int
    quotation_number: str
    customer_name: str
    status: str
    estimated_shipments: int
    estimated_cost: Decimal
    is_manual_override: bool
    consolidation_available: bool
    #: AWAITING_BILL | PAYMENT_PENDING | PAID. Goods ship after the money
    #: arrives, so the screen needs this to say why it cannot ship yet rather
    #: than offering a button the service will refuse.
    billing_state: str
    allocations: list[AllocationOut]

    @staticmethod
    def resolve_billing_state(obj) -> str:
        from apps.billing import services as billing

        state, _ = billing.billing_state(obj.quotation)
        return state

    @staticmethod
    def resolve_quotation_number(obj) -> str:
        return obj.quotation.number

    @staticmethod
    def resolve_customer_name(obj) -> str:
        return obj.quotation.customer.name


class OverrideRowIn(Schema):
    quotation_line_id: int
    warehouse_id: int
    quantity: int


class OverrideIn(Schema):
    allocations: list[OverrideRowIn]


class RestockIn(Schema):
    quantity: int


@router.get("/warehouses", response=list[WarehouseOut])
def list_warehouses(request):
    require_role(request, *VIEW_ROLES)
    return list(Warehouse.objects.all())


@router.get("/stock", response=list[StockRowOut])
def list_stock(request, warehouse_id: int | None = None, product_id: int | None = None):
    require_role(request, *VIEW_ROLES)
    qs = StockItem.objects.select_related("warehouse", "product")
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if product_id:
        qs = qs.filter(product_id=product_id)
    return list(qs.order_by("product__name", "warehouse__name"))


@router.get("/orders", response=list[OrderAwaitingOut])
def orders_awaiting(request):
    """Confirmed orders that still need shipping.

    "Still" is the operative word: this used to return every confirmed order
    ever placed, so a fully despatched one sat in the queue forever and the
    table could never empty. An order leaves once its plan reaches SHIPPED —
    a PARTIALLY_SHIPPED plan stays, because its backorder is exactly the work
    this screen exists to surface.
    """
    require_role(request, *VIEW_ROLES)
    rows = []
    quotations = (
        Quotation.objects.filter(status=QuotationStatus.CONFIRMED)
        .select_related("customer")
        .prefetch_related("fulfillment_plans__allocations__warehouse")
    )
    for quotation in quotations:
        plan = quotation.fulfillment_plans.first()
        if plan is not None and plan.status == FulfillmentStatus.SHIPPED:
            continue
        warehouses = (
            ", ".join(
                sorted({a.warehouse.name for a in plan.allocations.all()})
            )
            if plan
            else "—"
        )
        rows.append(
            {
                "quotation_id": quotation.id,
                "quotation_number": quotation.number,
                "customer_name": quotation.customer.name,
                "status": plan.status if plan else "Split Pending",
                "warehouses": warehouses,
                "plan_id": plan.id if plan else None,
            }
        )
    return rows


@router.post("/quotations/{quotation_id}/plan", response=PlanOut)
def create_plan(request, quotation_id: int):
    """Compute the suggested split for a confirmed order."""
    require_role(request, *VIEW_ROLES)
    try:
        quotation = Quotation.objects.select_related("customer").get(pk=quotation_id)
    except Quotation.DoesNotExist:
        raise NotFound("Quotation not found")
    return services.suggest_plan(quotation)


@router.get("/plans/{plan_id}", response=PlanOut)
def get_plan(request, plan_id: int):
    require_role(request, *VIEW_ROLES)
    return _get_plan(plan_id)


@router.post("/plans/{plan_id}/accept", response=PlanOut)
def accept_plan(request, plan_id: int):
    """Accept Suggested Split — reserves the stock.

    Finance/Ops only. The brief puts warehouse splits and backorder decisions
    with the Finance / Operations user, and accepting a split COMMITS stock:
    it moves quantity into `reserved`, which makes it unavailable to every other
    open deal. That is the same weight of decision as overriding the split, so
    it carries the same guard rather than being open to any signed-in user.
    """
    require_role(request, Role.FINANCE)
    return services.accept_plan(_get_plan(plan_id), actor=request.auth)


@router.post("/plans/{plan_id}/ship", response=PlanOut)
def ship_plan(request, plan_id: int):
    """Mark Shipped — the last step of the order lifecycle.

    Same Finance/Ops guard as accepting a split, and for a stronger reason:
    this one deducts stock and tells the customer their goods are on the way.
    The service refuses an order that has not been paid.
    """
    require_role(request, Role.FINANCE)
    return services.mark_shipped(_get_plan(plan_id), actor=request.auth)


@router.post("/plans/{plan_id}/override", response=PlanOut)
def override_plan(request, plan_id: int, payload: OverrideIn):
    """Manual Override — a named human decides who ships what."""
    require_role(request, Role.FINANCE)
    return services.override_plan(
        _get_plan(plan_id), [row.dict() for row in payload.allocations], actor=request.auth
    )


@router.post("/plans/{plan_id}/consolidate", response=PlanOut)
def consolidate_plan(request, plan_id: int):
    """Consolidate Remaining Backorder — re-plans only the backordered rows.

    Only reachable once a RESTOCK has set `consolidation_available`; the prompt
    exists because stock arrived, not because someone refreshed.
    """
    require_role(request, Role.FINANCE)
    return services.consolidate_backorders(_get_plan(plan_id), actor=request.auth)


@router.post("/stock/{stock_item_id}/restock", response=StockRowOut)
def restock(request, stock_item_id: int, payload: RestockIn):
    """Receive stock. Fires the backorder-consolidation check as a side effect."""
    require_role(request, Role.FINANCE)
    try:
        item = StockItem.objects.select_related("warehouse", "product").get(pk=stock_item_id)
    except StockItem.DoesNotExist:
        raise NotFound("Stock item not found")
    return services.restock(item, payload.quantity, actor=request.auth)


def _get_plan(plan_id: int) -> FulfillmentPlan:
    try:
        return FulfillmentPlan.objects.select_related("quotation", "quotation__customer").get(
            pk=plan_id
        )
    except FulfillmentPlan.DoesNotExist:
        raise NotFound("Fulfillment plan not found")

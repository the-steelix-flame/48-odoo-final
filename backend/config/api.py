"""The single NinjaAPI instance and its router registry.

This is the ONE shared file every lane edits, and only to add a line. Add your
router in your first commit so the file settles early and stops causing
conflicts. Keep the imports alphabetical-ish by lane owner.
"""

from ninja import NinjaAPI

from apps.common.errors import register_exception_handlers

api = NinjaAPI(
    title="DealFlow360 API",
    version="1.0.0",
    description="Self-governing sales operations platform.",
    docs_url="/docs",
)

register_exception_handlers(api)

# --- sinjeki --------------------------------------------------------------
from apps.accounts.api import router as accounts_router  # noqa: E402
from apps.catalog.api import router as catalog_router  # noqa: E402
from apps.governance.api import router as governance_router  # noqa: E402

api.add_router("/auth/", accounts_router, tags=["auth"])
api.add_router("/catalog/", catalog_router, tags=["catalog"])
api.add_router("/governance/", governance_router, tags=["governance"])

# --- the-steelix-flame ----------------------------------------------------
from apps.accounts.admin_api import router as admin_router  # noqa: E402
from apps.approvals.api import router as approvals_router  # noqa: E402
from apps.negotiation.api import router as portal_router  # noqa: E402
from apps.quotations.api import router as quotations_router  # noqa: E402

api.add_router("/quotations/", quotations_router, tags=["quotations"])
api.add_router("/approvals/", approvals_router, tags=["approvals"])
api.add_router("/portal/", portal_router, tags=["portal"])
api.add_router("/admin/", admin_router, tags=["admin"])

# --- anubhaw0raj ----------------------------------------------------------
from apps.billing.api import router as billing_router  # noqa: E402
from apps.fulfillment.api import router as fulfillment_router  # noqa: E402
from apps.insights.api import router as insights_router  # noqa: E402
from apps.subscriptions.api import router as subscriptions_router  # noqa: E402

api.add_router("/fulfillment/", fulfillment_router, tags=["fulfillment"])
api.add_router("/subscriptions/", subscriptions_router, tags=["subscriptions"])
api.add_router("/billing/", billing_router, tags=["billing"])
api.add_router("/insights/", insights_router, tags=["insights"])

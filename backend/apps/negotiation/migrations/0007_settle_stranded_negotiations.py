"""Repair quotations that violate the one-open-round invariant.

`submit_request` now refuses to stack a second request on an unanswered one,
but nothing stopped it before, and resolving the newer request left the older
one orphaned at SUBMITTED. The quotation moved on — re-approved, back to
APPROVED — while the inbox kept counting a request that no screen placed on the
board, because the board reads status and the inbox reads open requests.

This does NOT close the orphans. An unanswered customer request is real work,
and silently marking it rejected would answer the customer on the rep's behalf.
It moves the quotation to where that work is visible instead: UNDER_NEGOTIATION,
which is what an open round has always meant. Accepting or declining it from the
inbox now settles the quotation back out again, via `_settle_round`.
"""

from django.db import migrations

OPEN_REQUEST_STATUSES = ("SUBMITTED", "COUNTERED")
#: Only states a negotiation can legitimately be reopened from. CONFIRMED,
#: REJECTED and CANCELLED are terminal — an orphan there is history, not work,
#: and dragging a confirmed order back into negotiation would be worse than the
#: inconsistency it fixes.
REOPENABLE = ("SENT", "APPROVED")


def settle_stranded(apps, schema_editor):
    Quotation = apps.get_model("quotations", "Quotation")
    stranded = Quotation.objects.filter(
        status__in=REOPENABLE,
        negotiation_requests__status__in=OPEN_REQUEST_STATUSES,
    ).distinct()
    stranded.update(status="UNDER_NEGOTIATION")


def noop(apps, schema_editor):
    """Deliberately not reversible.

    The prior status is not recorded anywhere, so an automatic reverse would
    have to guess between SENT and APPROVED and would get it wrong half the
    time. Reversing this migration simply leaves the repaired rows repaired.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("negotiation", "0006_backfill_negotiation_events"),
        ("quotations", "0001_initial"),
    ]

    operations = [migrations.RunPython(settle_stranded, noop)]

"""Backfill the event log from existing messages and requests.

The timeline used to be derived from current state; it is now a straight read
of `negotiation_event`. Without this, every conversation that already exists —
including any mid-demo — would render empty on both sides.

Reconstructs what can be known:
  * each NegotiationMessage becomes a MESSAGE event
  * each NegotiationRequest becomes a COUNTER_REQUEST event at created_at
  * a resolved request additionally yields REP_COUNTER / ACCEPTED / REJECTED
    at resolved_at

A request that was countered and then accepted can only contribute the final
ACCEPTED, because the intermediate state was overwritten in place — that lost
history is exactly what the new table exists to stop happening again.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    NegotiationEvent = apps.get_model("negotiation", "NegotiationEvent")
    NegotiationMessage = apps.get_model("negotiation", "NegotiationMessage")
    NegotiationRequest = apps.get_model("negotiation", "NegotiationRequest")

    if NegotiationEvent.objects.exists():
        return  # already populated; never double up

    def author_name(author, quotation, author_type):
        if author_type == "CUSTOMER":
            return quotation.customer.name
        if author is None:
            return "System"
        return author.full_name or author.email

    rows = []

    for message in NegotiationMessage.objects.select_related(
        "thread__quotation__customer", "author", "quotation_line"
    ):
        quotation = message.thread.quotation
        rows.append(
            NegotiationEvent(
                quotation=quotation,
                kind="MESSAGE",
                author_type=message.author_type,
                author=message.author,
                author_name=author_name(message.author, quotation, message.author_type),
                body=message.body,
                quotation_line=message.quotation_line,
                created_at=message.created_at,
                updated_at=message.created_at,
            )
        )

    for request in NegotiationRequest.objects.select_related(
        "quotation__customer", "resolved_by"
    ):
        quotation = request.quotation
        rows.append(
            NegotiationEvent(
                quotation=quotation,
                request=request,
                kind="COUNTER_REQUEST",
                author_type="CUSTOMER",
                author_name=quotation.customer.name,
                body=request.message,
                discount_percent=request.requested_discount_percent,
                delivery_date=request.requested_delivery_date,
                created_at=request.created_at,
                updated_at=request.created_at,
            )
        )

        if request.status == "SUBMITTED" or request.resolved_at is None:
            continue

        kind = {
            "ACCEPTED": "ACCEPTED",
            "REJECTED": "REJECTED",
            "COUNTERED": "REP_COUNTER",
        }.get(request.status)
        if kind is None:
            continue

        rows.append(
            NegotiationEvent(
                quotation=quotation,
                request=request,
                kind=kind,
                author_type="REP",
                author=request.resolved_by,
                author_name=author_name(request.resolved_by, quotation, "REP"),
                body=request.resolution_note,
                # Rows created before `counter_discount_percent` was made
                # nullable carry 0.00 rather than NULL, so a plain acceptance
                # would render as "Agreed at 0%". Only trust the counter when
                # it holds a real offer.
                discount_percent=(
                    request.counter_discount_percent
                    if request.counter_discount_percent
                    else request.requested_discount_percent
                ),
                created_at=request.resolved_at,
                updated_at=request.resolved_at,
            )
        )

    # `auto_now_add` on created_at would stamp "now" on every row and flatten
    # the chronology, so bulk_create writes the historical values directly.
    NegotiationEvent.objects.bulk_create(rows, batch_size=200)


def unbackfill(apps, schema_editor):
    apps.get_model("negotiation", "NegotiationEvent").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("negotiation", "0005_negotiationevent")]

    operations = [migrations.RunPython(backfill, unbackfill)]

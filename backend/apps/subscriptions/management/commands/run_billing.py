"""Renew every subscription that is due.

    python manage.py run_billing
    python manage.py run_billing --as-of 2026-10-01     # let the demo time-travel
    python manage.py run_billing --dry-run

In production this is a nightly Celery beat. As a command it does the same
work and lets us show a renewal happening on stage without waiting a month.
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.common.enums import SubscriptionStatus
from apps.subscriptions.models import Subscription
from apps.subscriptions.services import renew


class Command(BaseCommand):
    help = "Issue recurring invoices for subscriptions due on or before a date."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", type=str, help="YYYY-MM-DD (default: today)")
        parser.add_argument(
            "--dry-run", action="store_true", help="List what would be billed, change nothing"
        )

    def handle(self, *args, **options):
        as_of: date = (
            datetime.strptime(options["as_of"], "%Y-%m-%d").date()
            if options.get("as_of")
            else timezone.now().date()
        )
        due = Subscription.objects.filter(
            status=SubscriptionStatus.ACTIVE, next_bill_date__lte=as_of
        ).select_related("customer", "plan", "product")

        if not due:
            self.stdout.write(f"Nothing due on or before {as_of}.")
            return

        for subscription in due:
            label = f"{subscription.customer.name} — {subscription.plan.name}"
            if options["dry_run"]:
                self.stdout.write(f"[dry-run] would renew {label} (due {subscription.next_bill_date})")
                continue
            event = renew(subscription)
            if event and event.invoice:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Renewed {label}: {event.invoice.number} for {event.invoice.total}"
                    )
                )

        verb = "Would renew" if options["dry_run"] else "Renewed"
        self.stdout.write(f"{verb} {len(due)} subscription(s) as of {as_of}.")

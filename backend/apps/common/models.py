from django.db import models

#: Money and percentage column shapes. Import these instead of retyping the
#: precision — inconsistent decimal places is how totals stop reconciling.
MONEY = dict(max_digits=12, decimal_places=2, default=0)
PERCENT = dict(max_digits=5, decimal_places=2, default=0)
QUANTITY = dict(max_digits=10, decimal_places=2, default=1)


def money(**overrides):
    """`DecimalField(**money(default=30))` — same precision, different default.

    Spreading MONEY directly and then passing `default=` again is a TypeError,
    so use this whenever you need to override anything in the base shape.
    """
    return {**MONEY, **overrides}


def percent(**overrides):
    return {**PERCENT, **overrides}


def quantity(**overrides):
    return {**QUANTITY, **overrides}


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

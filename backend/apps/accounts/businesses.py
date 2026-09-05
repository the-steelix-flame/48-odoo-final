"""Business (customer company) onboarding.  Owner: the-steelix-flame.

An admin registers a company you sell to, and the system mints a portal login
for them. The generated password is shown to the admin EXACTLY ONCE and is
never recoverable afterwards — it goes straight into Django's hasher, same as
any other account. "Show me the password again" is deliberately impossible;
the answer is always "reset it and hand over a new one".

Later, when real email is wired up, `create_business` is the natural place to
send the credentials directly instead of returning them to the caller.

NOTE FOR @sinjeki: this is a NEW file inside your `accounts` app rather than an
edit to `models.py` or `api.py`, so it should never conflict with your work. It
needs no migration — portal access is toggled through the existing
`User.is_active`, and issuance is dated from `User.date_joined`.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from django.db import transaction

from apps.accounts.models import Customer, User
from apps.common.enums import CustomerTier, Role
from apps.common.errors import ValidationError

#: Ambiguous glyphs removed — these passwords get read aloud, retyped off a
#: screenshot, and pasted into chat. `l/1/I` and `O/0` cost support time.
_ALPHABET = (
    "".join(c for c in string.ascii_letters if c not in "lIO")
    + "".join(c for c in string.digits if c not in "01")
)
PASSWORD_LENGTH = 12


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


@dataclass
class OnboardingResult:
    """`password` is populated only on the call that created or reset it."""

    customer: Customer
    portal_user: User | None
    password: str | None


@transaction.atomic
def create_business(
    *,
    name: str,
    contact_email: str,
    tier: str = CustomerTier.BRONZE,
    currency: str = "USD",
    owner_rep_id: int | None = None,
    default_price_list_id: int | None = None,
    create_portal_login: bool = True,
    actor: User | None = None,
) -> OnboardingResult:
    """Register a business and optionally mint its portal login."""
    name = (name or "").strip()
    contact_email = (contact_email or "").strip().lower()

    if not name:
        raise ValidationError("A business name is required")
    if Customer.objects.filter(name__iexact=name).exists():
        raise ValidationError(f"A business called “{name}” already exists")
    if tier not in CustomerTier.values:
        raise ValidationError(f"Unknown tier {tier}")

    if create_portal_login:
        if not contact_email:
            raise ValidationError("A contact email is required to create a portal login")
        if User.objects.filter(email__iexact=contact_email).exists():
            raise ValidationError(
                f"{contact_email} already has an account. Use a different contact address, "
                "or reset that account's password instead."
            )

    customer = Customer.objects.create(
        name=name,
        tier=tier,
        currency=currency,
        contact_email=contact_email,
        owner_rep_id=owner_rep_id,
        default_price_list_id=default_price_list_id,
    )

    portal_user = None
    password = None
    if create_portal_login:
        password = generate_password()
        portal_user = User.objects.create_user(
            email=contact_email,
            password=password,
            full_name=f"{name} (portal)",
            role=Role.CUSTOMER,
        )
        customer.portal_user = portal_user
        customer.save(update_fields=["portal_user", "updated_at"])

    return OnboardingResult(customer=customer, portal_user=portal_user, password=password)


@transaction.atomic
def issue_portal_login(customer: Customer, *, actor: User | None = None) -> OnboardingResult:
    """Create a portal login for a business that was registered without one."""
    if customer.portal_user_id:
        raise ValidationError(
            f"{customer.name} already has a portal login. Reset its password instead."
        )
    if not customer.contact_email:
        raise ValidationError("Set a contact email on this business first")
    if User.objects.filter(email__iexact=customer.contact_email).exists():
        raise ValidationError(f"{customer.contact_email} already has an account")

    password = generate_password()
    portal_user = User.objects.create_user(
        email=customer.contact_email.lower(),
        password=password,
        full_name=f"{customer.name} (portal)",
        role=Role.CUSTOMER,
    )
    customer.portal_user = portal_user
    customer.save(update_fields=["portal_user", "updated_at"])
    return OnboardingResult(customer=customer, portal_user=portal_user, password=password)


@transaction.atomic
def reset_portal_password(customer: Customer, *, actor: User | None = None) -> OnboardingResult:
    """Mint a fresh password. The old one stops working immediately."""
    user = customer.portal_user
    if user is None:
        raise ValidationError(f"{customer.name} has no portal login to reset")

    password = generate_password()
    user.set_password(password)
    # A reset is also how you recover a disabled account, so re-enable it.
    user.is_active = True
    user.save(update_fields=["password", "is_active"])
    return OnboardingResult(customer=customer, portal_user=user, password=password)


@transaction.atomic
def set_portal_access(customer: Customer, *, enabled: bool, actor: User | None = None) -> Customer:
    """Suspend or restore a business's portal access.

    Deliberately toggles `is_active` rather than deleting the user: their
    negotiation history, comments and counter-offers stay attached to the
    quotations they belong to. Revoking access must not rewrite the audit trail.
    """
    user = customer.portal_user
    if user is None:
        raise ValidationError(f"{customer.name} has no portal login")
    user.is_active = enabled
    user.save(update_fields=["is_active"])
    return customer

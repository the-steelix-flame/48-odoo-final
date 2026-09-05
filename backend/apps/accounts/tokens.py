"""Session tokens.

Phase 1 (today): a signed, expiring token minted by us. Not a JWT, not a
session cookie — just enough to carry identity over the wire honestly. Passwords
are still checked with Django's real hasher, so this is a *simplified* auth
system, not a fake one.

Phase 2 (end of day): `resolve_token` learns to verify a Firebase ID token and
look the user up by `firebase_uid`. Nothing above this module changes.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

from apps.accounts.models import User
from apps.common.errors import PermissionDenied

_SALT = "dealflow360.auth"


def mint_token(user: User) -> str:
    return signing.dumps({"uid": user.pk, "role": user.role}, salt=_SALT)


def resolve_token(token: str) -> User:
    """Token string -> User, or raise. The single entry point for auth."""
    if settings.USE_FIREBASE_AUTH:
        return _resolve_firebase_token(token)

    max_age = timedelta(hours=settings.AUTH_TOKEN_TTL_HOURS).total_seconds()
    try:
        payload = signing.loads(token, salt=_SALT, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise PermissionDenied("Session expired") from exc
    except signing.BadSignature as exc:
        raise PermissionDenied("Not authenticated") from exc

    try:
        return User.objects.select_related("sales_team").get(pk=payload["uid"], is_active=True)
    except User.DoesNotExist as exc:
        raise PermissionDenied("Not authenticated") from exc


def _resolve_firebase_token(token: str) -> User:
    """Phase 2. Verify with Firebase, then map to our own user row.

    Deliberately still reads `role` from Postgres rather than from a Firebase
    custom claim: Firebase proves who you are, our database decides what you
    may do. That's what makes the swap a one-file change.
    """
    import firebase_admin  # noqa: F401  (imported lazily; not a day-1 dependency)
    from firebase_admin import auth as firebase_auth

    try:
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:  # noqa: BLE001 - any verification failure is a 401
        raise PermissionDenied("Not authenticated") from exc

    try:
        return User.objects.select_related("sales_team").get(
            firebase_uid=decoded["uid"], is_active=True
        )
    except User.DoesNotExist as exc:
        raise PermissionDenied("No DealFlow account linked to this identity") from exc


def touch_last_login(user: User) -> None:
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])

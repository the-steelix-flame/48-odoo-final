from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.common.enums import CustomerTier, Role
from apps.common.models import TimeStampedModel


class UserManager(BaseUserManager):
    """Email-based manager. `username` doesn't exist on this model."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Users must have an email address")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        return self.create_user(email, password, **extra)


class SalesTeam(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    manager = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_teams",
    )

    class Meta:
        db_table = "sales_team"

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Internal staff and portal customers share one table.

    `role` is a plain column rather than a Django Group. One field, one source
    of truth, read directly by the Ninja auth dependency. Groups would buy us
    nothing at five roles and would put authorisation in two places.
    """

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SALES_REP)
    sales_team = models.ForeignKey(
        SalesTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    #: Populated only once Firebase auth is switched on (phase 2). Identity
    #: comes from Firebase; authorisation always stays here in Postgres.
    firebase_uid = models.CharField(max_length=128, unique=True, null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "app_user"

    def __str__(self) -> str:
        return f"{self.full_name or self.email} ({self.role})"

    @property
    def is_internal(self) -> bool:
        return self.role != Role.CUSTOMER


class Customer(TimeStampedModel):
    name = models.CharField(max_length=150)
    tier = models.CharField(
        max_length=10, choices=CustomerTier.choices, default=CustomerTier.BRONZE
    )
    currency = models.CharField(max_length=3, default="USD")
    contact_email = models.EmailField(blank=True)

    #: Where this business receives goods, as the admin typed it. `latitude` /
    #: `longitude` are the resolved point the fulfillment planner ranks
    #: warehouses against — nullable because every row that predates this field
    #: has none, and allocation has to keep working for them.
    address = models.CharField(max_length=250, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    #: Set when the point came from geocoding the address, null when a human
    #: typed it. Lets a re-geocode skip rows someone corrected by hand.
    geocoded_at = models.DateTimeField(null=True, blank=True)

    owner_rep = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="owned_customers"
    )
    #: The CUSTOMER-role login that may open this customer's portal.
    portal_user = models.OneToOneField(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="customer_profile"
    )
    default_price_list = models.ForeignKey(
        "catalog.PriceList", null=True, blank=True, on_delete=models.SET_NULL, related_name="customers"
    )

    class Meta:
        db_table = "customer"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.tier}]"

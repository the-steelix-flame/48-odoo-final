from ninja import Schema


class LoginIn(Schema):
    email: str
    password: str


class SignupIn(Schema):
    email: str
    password: str
    full_name: str
    role: str = "SALES_REP"


class UserOut(Schema):
    id: int
    email: str
    full_name: str
    role: str
    sales_team_id: int | None = None
    sales_team_name: str | None = None

    @staticmethod
    def resolve_sales_team_name(obj) -> str | None:
        return obj.sales_team.name if obj.sales_team_id else None


class AuthOut(Schema):
    token: str
    user: UserOut


class CustomerOut(Schema):
    id: int
    name: str
    tier: str
    currency: str
    contact_email: str
    owner_rep_id: int | None = None
    default_price_list_id: int | None = None


class CustomerIn(Schema):
    name: str
    tier: str = "BRONZE"
    currency: str = "USD"
    contact_email: str = ""
    owner_rep_id: int | None = None

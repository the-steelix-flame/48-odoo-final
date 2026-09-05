"""Product catalog & price lists (screens 16, 17).  Owner: sinjeki."""

from ninja import Router

from apps.accounts.auth import internal_auth, require_role
from apps.catalog.models import PriceList, Product, ProductCategory
from apps.catalog.schemas import (
    CategoryOut,
    PriceListOut,
    ProductDetailOut,
    ProductIn,
    ProductOut,
)
from apps.common.enums import Role
from apps.common.errors import NotFound

router = Router(auth=internal_auth)


@router.get("/categories", response=list[CategoryOut])
def list_categories(request):
    return list(ProductCategory.objects.all())


@router.get("/products", response=list[ProductOut])
def list_products(request, category_id: int | None = None, q: str | None = None):
    qs = Product.objects.select_related("category").filter(is_active=True)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if q:
        qs = qs.filter(name__icontains=q)
    return list(qs)


@router.get("/products/{product_id}", response=ProductDetailOut)
def get_product(request, product_id: int):
    try:
        return Product.objects.select_related("category").get(pk=product_id)
    except Product.DoesNotExist:
        raise NotFound("Product not found")


@router.post("/products", response=ProductDetailOut)
def create_product(request, payload: ProductIn):
    require_role(request, Role.ADMIN)
    return Product.objects.create(**payload.dict())


@router.patch("/products/{product_id}", response=ProductDetailOut)
def update_product(request, product_id: int, payload: ProductIn):
    require_role(request, Role.ADMIN)
    updated = Product.objects.filter(pk=product_id).update(**payload.dict())
    if not updated:
        raise NotFound("Product not found")
    return Product.objects.select_related("category").get(pk=product_id)


@router.get("/price-lists", response=list[PriceListOut])
def list_price_lists(request):
    return list(PriceList.objects.filter(is_active=True))

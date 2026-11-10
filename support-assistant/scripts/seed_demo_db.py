"""Create a deterministic NovaRetail demo database dataset.

Run from ``support-assistant`` after migrations:
    python -m scripts.seed_demo_db
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import delete, select

from db.models import (
    CustomerModel,
    OrderItemModel,
    OrderModel,
    ProductModel,
    ProductPriceModel,
    ProductSpecModel,
    RefundRequest,
    Tenant,
)
from db.session import get_sync_session

TENANT_ID = "tenant_novaretail"
PRODUCT_COUNT = 2000
CUSTOMER_COUNT = 1000
ORDER_COUNT = 2500
REFUND_COUNT = 1000

CATEGORIES = (
    ("CPU", ("Intel", "AMD"), ("Core", "Ryzen")),
    ("GPU", ("NVIDIA", "AMD"), ("GeForce", "Radeon")),
    ("Motherboard", ("ASUS", "MSI", "Gigabyte"), ("Prime", "Pro", "Aorus")),
    ("Memory", ("Corsair", "Kingston", "G.Skill"), ("Vengeance", "Fury", "Ripjaws")),
    ("Storage", ("Samsung", "WD", "Crucial"), ("Pro", "Blue", "Plus")),
    ("Power Supply", ("Corsair", "Cooler Master", "Seasonic"), ("RM", "MWE", "Focus")),
    ("Cooling", ("Noctua", "DeepCool", "Arctic"), ("NH", "AK", "Liquid")),
    ("Case", ("NZXT", "Lian Li", "Fractal"), ("H", "Lancool", "Meshify")),
    ("Monitor", ("Dell", "LG", "Acer"), ("UltraSharp", "UltraGear", "Nitro")),
    ("Accessory", ("Logitech", "Razer", "TP-Link"), ("Pro", "Edge", "Archer")),
)
ORDER_STATUSES = ("Processing", "Shipped", "Delivered", "Cancelled")
REFUND_STATES = ("processed", "pending_approval", "approved", "rejected", "failed")
REFUND_AMOUNTS = (100, 499, 1499, 1999, 2000, 2001, 4999, 10000, 25000, 50000)


def _id(prefix: str, number: int) -> str:
    return f"{prefix}_{number:05d}"


def _phone_hash(number: int) -> str:
    return hashlib.sha256(f"+919900{number:06d}".encode()).hexdigest()


def _chunked(items: Iterable, size: int = 500):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _product_rows():
    for index in range(1, PRODUCT_COUNT + 1):
        category, brands, families = CATEGORIES[(index - 1) % len(CATEGORIES)]
        brand = brands[(index - 1) % len(brands)]
        family = families[(index - 1) % len(families)]
        name = f"{brand} {family} {100 + index:04d} {category}"
        product_id = _id("demo_prod", index)
        base_price = 499 + ((index * 7919) % 249501)
        discount = base_price - max(100, int(base_price * (5 + index % 16) / 100))
        description = (
            f"{name} is a reliable {category.lower()} for gaming, creation, and everyday computing. "
            "This demo listing includes realistic support content for catalog and refund testing."
        )
        faqs = [
            {"question": "Is this item covered by warranty?", "answer": "Yes, it includes a 12-month limited warranty."},
            {"question": "When will it ship?", "answer": "In-stock items usually ship within two business days."},
            {"question": "Can I return it?", "answer": "Physical items can be returned within 30 days when eligible."},
        ]
        specs = (
            ("interface", f"{['PCIe 4.0', 'PCIe 5.0', 'DDR5', 'USB-C'][index % 4]}", None),
            ("capacity", str(256 + ((index * 37) % 7936)), "GB"),
            ("power_draw", str(45 + ((index * 13) % 405)), "W"),
            ("warranty", "12", "months"),
        )
        yield (
            ProductModel(
                product_id=product_id,
                tenant_id=TENANT_ID,
                name=name,
                brand=brand,
                category=category,
                description=description,
                faqs=faqs,
                aliases=[f"{brand.lower()} {family.lower()} {100 + index:04d}", category.lower()],
                active=True,
            ),
            ProductPriceModel(
                product_id=product_id,
                price=base_price,
                discount_price=discount,
                currency="INR",
                in_stock=index % 17 != 0,
            ),
            [
                ProductSpecModel(
                    spec_id=f"{product_id}_spec_{spec_index}",
                    product_id=product_id,
                    spec_key=key,
                    spec_value=value,
                    unit=unit,
                )
                for spec_index, (key, value, unit) in enumerate(specs, start=1)
            ],
        )


def _delete_demo_rows(session) -> None:
    demo_order_ids = select(OrderModel.order_id).where(OrderModel.order_id.like("demo_order_%"))
    session.execute(delete(RefundRequest).where(RefundRequest.refund_id.like("demo_refund_%")))
    session.execute(delete(OrderItemModel).where(OrderItemModel.order_id.in_(demo_order_ids)))
    session.execute(delete(OrderModel).where(OrderModel.order_id.like("demo_order_%")))
    demo_customer_ids = select(CustomerModel.customer_id).where(CustomerModel.customer_id.like("demo_customer_%"))
    session.execute(delete(CustomerModel).where(CustomerModel.customer_id.in_(demo_customer_ids)))
    demo_product_ids = select(ProductModel.product_id).where(ProductModel.product_id.like("demo_prod_%"))
    session.execute(delete(ProductSpecModel).where(ProductSpecModel.product_id.in_(demo_product_ids)))
    session.execute(delete(ProductPriceModel).where(ProductPriceModel.product_id.in_(demo_product_ids)))
    session.execute(delete(ProductModel).where(ProductModel.product_id.like("demo_prod_%")))


def seed_demo_data(reset: bool = True) -> dict[str, int]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with get_sync_session(tenant_id=TENANT_ID) as session:
        tenant = session.get(Tenant, TENANT_ID)
        if tenant is None:
            session.add(Tenant(tenant_id=TENANT_ID, name="NovaRetail Demo Store"))
            session.flush()
        if reset:
            _delete_demo_rows(session)

        products = []
        prices = []
        specs = []
        for product, price, product_specs in _product_rows():
            products.append(product)
            prices.append(price)
            specs.extend(product_specs)
        session.add_all(products)
        session.add_all(prices)
        for batch in _chunked(specs):
            session.add_all(batch)
            session.flush()

        customers = [
            CustomerModel(
                customer_id=_id("demo_customer", index),
                tenant_id=TENANT_ID,
                phone_hash=_phone_hash(index),
                email=f"demo.customer{index:04d}@example.test",
                full_name=f"Demo Customer {index:04d}",
                language_pref=("en", "ta", "tanglish")[index % 3],
                created_at=now - timedelta(days=index % 730),
            )
            for index in range(1, CUSTOMER_COUNT + 1)
        ]
        session.add_all(customers)
        session.flush()

        order_items = []
        orders = []
        for index in range(1, ORDER_COUNT + 1):
            product_index = ((index * 17) % PRODUCT_COUNT) + 1
            product_id = _id("demo_prod", product_index)
            product = products[product_index - 1]
            quantity = 1 + (index % 3)
            unit_price = prices[product_index - 1].discount_price or prices[product_index - 1].price
            created_at = now - timedelta(days=index % 120, hours=index % 24)
            status = ORDER_STATUSES[index % len(ORDER_STATUSES)]
            order_id = _id("demo_order", index)
            orders.append(
                OrderModel(
                    order_id=order_id,
                    tenant_id=TENANT_ID,
                    customer_id=_id("demo_customer", ((index - 1) % CUSTOMER_COUNT) + 1),
                    total_amount_inr=unit_price * quantity,
                    status=status,
                    tracking_number=None if status in ("Processing", "Cancelled") else f"DEMO{index:012d}",
                    courier_name=None if status == "Cancelled" else ("Delhivery", "BlueDart", "DTDC")[index % 3],
                    shipping_address=f"{100 + index % 900}, Demo Avenue, Bengaluru, Karnataka",
                    created_at=created_at,
                    delivered_at=created_at + timedelta(days=5) if status == "Delivered" else None,
                )
            )
            order_items.append(
                OrderItemModel(
                    item_id=_id("demo_item", index),
                    order_id=order_id,
                    product_id=product_id,
                    product_name=product.name,
                    category=product.category,
                    price=unit_price,
                    quantity=quantity,
                    is_digital=False,
                    is_refunded=False,
                )
            )
        session.add_all(orders)
        session.add_all(order_items)
        session.flush()

        refunds = []
        for index in range(1, REFUND_COUNT + 1):
            order_number = ((index * 7 - 1) % ORDER_COUNT) + 1
            amount = REFUND_AMOUNTS[(index - 1) % len(REFUND_AMOUNTS)]
            state = REFUND_STATES[(index - 1) % len(REFUND_STATES)]
            refunds.append(
                RefundRequest(
                    refund_id=_id("demo_refund", index),
                    tenant_id=TENANT_ID,
                    order_id=_id("demo_order", order_number),
                    customer_id=_id("demo_customer", ((order_number - 1) % CUSTOMER_COUNT) + 1),
                    item_ref=_id("demo_item", order_number),
                    amount_inr=amount,
                    state=state,
                    idempotency_key=f"demo-refund-key-{index:05d}",
                    reason=("Damaged on arrival", "Wrong item received", "Changed my mind")[index % 3],
                    request_time=now - timedelta(days=index % 45),
                    eligibility_snapshot={
                        "within_return_window": index % 7 != 0,
                        "auto_refund_limit_inr": 2000,
                    },
                    policy_version_applied="demo-v1",
                )
            )
        session.add_all(refunds)
        session.commit()

    return {
        "products": PRODUCT_COUNT,
        "product_specs": PRODUCT_COUNT * 4,
        "customers": CUSTOMER_COUNT,
        "orders": ORDER_COUNT,
        "order_items": ORDER_COUNT,
        "refund_requests": REFUND_COUNT,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    counts = seed_demo_data()
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()

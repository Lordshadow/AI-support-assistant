from contextlib import contextmanager

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from db.models import (
    Base,
    CustomerModel,
    OrderModel,
    ProductModel,
    ProductSpecModel,
    RefundRequest,
)
import scripts.seed_demo_db as seed_demo_db


def test_seed_demo_data_creates_expected_catalog_and_transaction_ranges(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    @contextmanager
    def session_context(tenant_id=None):
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(seed_demo_db, "get_sync_session", session_context)
    assert seed_demo_db.seed_demo_data() == {
        "products": 2000,
        "product_specs": 8000,
        "customers": 1000,
        "orders": 2500,
        "order_items": 2500,
        "refund_requests": 1000,
    }

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ProductModel)) == 2000
        assert session.scalar(select(func.count()).select_from(ProductSpecModel)) == 8000
        assert session.scalar(select(func.count()).select_from(CustomerModel)) == 1000
        assert session.scalar(select(func.count()).select_from(OrderModel)) == 2500
        assert session.scalar(select(func.count()).select_from(RefundRequest)) == 1000
        first_product = session.scalar(select(ProductModel).limit(1))
        assert first_product.description
        assert len(first_product.faqs) == 3
        refund_amounts = set(session.scalars(select(RefundRequest.amount_inr)))
        assert {100, 1999, 2000, 2001, 50000}.issubset(refund_amounts)

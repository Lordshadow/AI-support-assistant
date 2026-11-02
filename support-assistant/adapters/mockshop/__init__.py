"""
MockShop Adapter Package
Exports concrete implementations of CatalogPort, OrderPort, and RefundPort.
"""

from .catalog_adapter import MockCatalogAdapter
from .order_adapter import MockOrderAdapter
from .refund_adapter import MockRefundAdapter

__all__ = [
    "MockCatalogAdapter",
    "MockOrderAdapter",
    "MockRefundAdapter",
]

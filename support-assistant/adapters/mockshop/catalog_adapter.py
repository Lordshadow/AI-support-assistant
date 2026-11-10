"""
MockShop Catalog Adapter
Implements CatalogPort protocol using structured in-memory catalog data.
Complies with Specification Section 6, 7.1, and 8 (Look-Alike Disambiguation).
"""

from typing import Optional, Any
import re
from core.models import ProductMatch, ProductSpecs, PriceInfo, ProductSummary


class MockCatalogAdapter:
    """In-memory concrete implementation of CatalogPort."""

    def __init__(self):
        # 1. Product Specifications & Aliases
        self._specs: dict[str, ProductSpecs] = {
            "P1041": ProductSpecs(
                product_id="P1041",
                name="Pulse Buds 141",
                brand="NovaAudio",
                category="electronics",
                specs={
                    "battery_life": "42 hours total playback (6 hours per bud)",
                    "driver_size": "10mm dynamic bass drivers",
                    "connectivity": "Bluetooth 5.2 (10m range)",
                    "water_resistance": "IPX4 water and sweat resistant",
                    "fast_charging": "10 min charge gives 75 min playtime",
                    "charging_port": "USB Type-C"
                },
                aliases=["pulse buds 141", "buds 141", "pb 141", "pb141", "141 buds"]
            ),
            "P1031": ProductSpecs(
                product_id="P1031",
                name="Pulse Buds 131",
                brand="NovaAudio",
                category="electronics",
                specs={
                    "battery_life": "60 hours total playback (8 hours per bud)",
                    "driver_size": "13mm sound drivers",
                    "connectivity": "Bluetooth 5.0",
                    "water_resistance": "IPX4 sweat resistant",
                    "fast_charging": "5 min charge gives 60 min playtime",
                    "charging_port": "USB Type-C"
                },
                aliases=["pulse buds 131", "buds 131", "pb 131", "pb131", "131 buds"]
            ),
            "P2001": ProductSpecs(
                product_id="P2001",
                name="Nova Watch Pro",
                brand="NovaTech",
                category="wearables",
                specs={
                    "display": "1.43-inch AMOLED (466x466 resolution)",
                    "battery_life": "Up to 7 days normal use, 14 days standby",
                    "health_sensors": "Heart rate, SpO2, Sleep tracking, Stress monitor",
                    "water_resistance": "3 ATM water resistant",
                    "connectivity": "Bluetooth 5.3 + GPS"
                },
                aliases=["nova watch pro", "watch pro", "nova watch"]
            ),
            "P-GIFT500": ProductSpecs(
                product_id="P-GIFT500",
                name="Google Play ₹500 Gift Card",
                brand="Google",
                category="digital",
                specs={
                    "denomination": "₹500 INR",
                    "delivery": "Instant digital code delivered via Email & SMS",
                    "validity": "No expiration date"
                },
                aliases=["google play gift card", "google gift card", "play store code"]
            )
        }

        # 2. Live Pricing and Stock
        self._prices: dict[str, PriceInfo] = {
            "P1041": PriceInfo(
                product_id="P1041",
                price=1499,
                discount_price=1299,
                currency="INR",
                in_stock=True,
                active_offers=["10% instant discount on ICICI cards"]
            ),
            "P1031": PriceInfo(
                product_id="P1031",
                price=1199,
                discount_price=999,
                currency="INR",
                in_stock=True,
                active_offers=["₹100 coupon on first order"]
            ),
            "P2001": PriceInfo(
                product_id="P2001",
                price=4500,
                discount_price=3999,
                currency="INR",
                in_stock=True,
                active_offers=["Free extra silicon strap"]
            ),
            "P-GIFT500": PriceInfo(
                product_id="P-GIFT500",
                price=500,
                discount_price=None,
                currency="INR",
                in_stock=True
            )
        }

        # 3. Product-restricted Document Chunks
        self._docs: dict[str, list[str]] = {
            "P1041": [
                "Pulse Buds 141 - Battery life: Provides up to 42 hours of total playback time with the charging case. Each earbud provides 6 hours on a single charge.",
                "Pulse Buds 141 - Pairing: Open the charging case near your smartphone and select 'Pulse Buds 141' from available Bluetooth devices.",
                "Pulse Buds 141 - Warranty: Comes with a 1-year limited warranty against manufacturing defects."
            ],
            "P1031": [
                "Pulse Buds 131 - Battery life: Delivers up to 60 hours of total playtime with the case. Individual buds last up to 8 hours.",
                "Pulse Buds 131 - Audio: Powered by 13mm dynamic drivers for crisp vocals and punchy sound."
            ],
            "P2001": [
                "Nova Watch Pro - Battery: The 300mAh battery delivers up to 7 days of normal usage and charges in 90 minutes via magnetic puck.",
                "Nova Watch Pro - Sensors: Continuous heart rate monitoring, real-time blood oxygen (SpO2), and step tracking."
            ],
            "P-GIFT500": [
                "Google Play ₹500 Gift Card - Redemption: Open the Google Play Store app, tap Profile > Payments & subscriptions > Redeem code, and enter the 16-digit voucher.",
                "Google Play Gift Cards are digital goods delivered electronically and are non-refundable once issued."
            ]
        }

        # 4. Store Policies
        self._policies: list[str] = [
            "Policy Clause 1.0 (Return Window): Physical items can be returned within 30 days of confirmed delivery if unused and in original packaging.",
            "Policy Clause 2.0 (Refund Timelines): Approved refunds process back to the original payment method within 3–5 business days.",
            "Policy Clause 3.0 (Damaged Items): If an item arrives broken or defective, NovaRetail provides a free prepaid return label or expedited replacement without charging return shipping.",
            "Policy Clause 6.0 (Digital Goods): Digital game codes, gift cards, and software licenses are strictly non-refundable once delivered.",
            "Policy Clause 7.0 (Address Changes): Shipping address changes are only permitted within 2 hours of ordering while the order is in 'Processing' status."
        ]

    async def find_product(self, text: str) -> list[ProductMatch]:
        """
        Fuzzy & Token-based resolution.
        Handles look-alikes like 'Pulse Buds 141' vs 'Pulse Buds 131'.
        """
        query = text.lower().strip()
        matches: list[ProductMatch] = []

        for p_id, specs in self._specs.items():
            score = 0.0
            name_lower = specs.name.lower()

            # Exact match
            if query == name_lower or query in specs.aliases:
                score = 0.98
            # Exact model number token match (e.g. "141" or "131")
            elif ("141" in query and "141" in name_lower) or ("131" in query and "131" in name_lower):
                score = 0.92
            # Look-alike broad query (e.g. "pulse buds")
            elif (
                "pulse" in query
                and "buds" in query
                and not re.search(r"\b(?:141|131)\b", query)
                and "pulse buds" in name_lower
            ):
                score = 0.85
            elif any(alias in query for alias in specs.aliases):
                score = 0.80
            elif query in specs.name.lower() or specs.category.lower() in query:
                score = 0.65

            if score > 0.5:
                matches.append(ProductMatch(
                    product_id=p_id,
                    name=specs.name,
                    score=score,
                    category=specs.category
                ))

        # Sort highest score first
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    async def get_details(self, product_id: str) -> Optional[ProductSpecs]:
        return self._specs.get(product_id)

    async def get_price(self, product_id: str) -> Optional[PriceInfo]:
        return self._prices.get(product_id)

    async def search(
        self,
        category: Optional[str] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        filters: Optional[dict] = None
    ) -> list[ProductSummary]:
        results: list[ProductSummary] = []
        for p_id, specs in self._specs.items():
            if category and specs.category.lower() != category.lower():
                continue
            price_info = self._prices.get(p_id)
            if not price_info:
                continue
            effective_price = price_info.discount_price or price_info.price
            if min_price is not None and effective_price < min_price:
                continue
            if max_price is not None and effective_price > max_price:
                continue
            results.append(ProductSummary(
                product_id=p_id,
                name=specs.name,
                category=specs.category,
                price=effective_price,
                in_stock=price_info.in_stock
            ))
        return results

    async def search_product_docs(self, product_id: str, query: str) -> list[str]:
        """Returns chunks strictly bound to product_id."""
        docs = self._docs.get(product_id, [])
        query_words = self._content_terms(query)
        matched = []
        for d in docs:
            d_words = self._content_terms(d)
            if query_words & d_words:
                matched.append(d)
        return matched

    async def search_policy(self, query: str) -> list[str]:
        query_words = self._content_terms(query)
        scored = []
        for p in self._policies:
            p_words = self._content_terms(p)
            score = len(query_words & p_words)
            if score:
                scored.append((score, p))
        if not scored:
            return []
        best_score = max(score for score, _ in scored)
        return [clause for score, clause in scored if score == best_score]

    def export_catalog(self) -> list[dict[str, Any]]:
        """
        Export catalog products for knowledge ingestion.
        Excludes price, stock, offers, or order status (always fetched live).
        Specifications are structured relationally for product_specs.
        """
        descriptions = {
            "P1041": "Pulse Buds 141 deliver high fidelity wireless audio with environmental noise cancellation. Equipped with ASAP charge technology and IPX4 splash resistance for everyday active use.",
            "P1031": "Pulse Buds 131 feature powerful 13mm dynamic drivers and extra long battery playback. Ergonomic semi-in-ear design provides lasting comfort and punchy bass.",
            "P2001": "Nova Watch Pro is an enterprise smartwatch with an AMOLED always-on display, multi-sport activity tracking, and comprehensive biometric monitoring.",
            "P-GIFT500": "Google Play ₹500 digital gift voucher code for apps, games, movies, and in-app subscriptions across Android devices.",
        }
        faqs_map = {
            "P1041": [
                {"question": "How long does the battery last on Pulse Buds 141?", "answer": "Pulse Buds 141 offers up to 42 hours total playback with the case and 6 hours per charge."},
                {"question": "Does Pulse Buds 141 support fast charging?", "answer": "Yes, ASAP charge gives 75 minutes of playtime with just 10 minutes of charging."},
                {"question": "Is Pulse Buds 141 water resistant?", "answer": "Pulse Buds 141 is rated IPX4 for water and sweat resistance."},
                {"question": "What is the warranty period for Pulse Buds 141?", "answer": "It includes a 1-year brand warranty covering manufacturing defects."},
            ],
            "P1031": [
                {"question": "What is the battery backup of Pulse Buds 131?", "answer": "Pulse Buds 131 provides up to 60 hours total playback and 8 hours on earbuds."},
                {"question": "What size are the audio drivers in Pulse Buds 131?", "answer": "It is equipped with 13mm dynamic sound drivers for enhanced bass."},
                {"question": "Does Pulse Buds 131 have Type-C charging?", "answer": "Yes, it charges via a standard USB Type-C charging port."},
            ],
            "P2001": [
                {"question": "How long does Nova Watch Pro battery last?", "answer": "The 300mAh battery delivers up to 7 days of normal use and 14 days standby."},
                {"question": "Does Nova Watch Pro track sleep and SpO2?", "answer": "Yes, it provides 24/7 continuous heart rate, SpO2 blood oxygen, and sleep stage tracking."},
                {"question": "Is Nova Watch Pro swim-proof?", "answer": "It features 3 ATM water resistance suitable for splashes and swimming."},
            ],
            "P-GIFT500": [
                {"question": "How do I redeem my Google Play gift card?", "answer": "Open Google Play Store, go to Profile > Payments & subscriptions > Redeem code, and enter your 16-digit code."},
                {"question": "Can I return a digital gift card?", "answer": "No, per Store Policy Clause 6.0 digital gift cards are strictly non-refundable once delivered."},
            ],
        }

        exported = []
        for pid, spec in self._specs.items():
            specs_list = [{"label": k, "value": v} for k, v in spec.specs.items()]
            exported.append({
                "product_id": pid,
                "name": spec.name,
                "brand": spec.brand,
                "category": spec.category,
                "description": descriptions.get(pid, f"{spec.name} - Official product specification and user documentation."),
                "faqs": faqs_map.get(pid, []),
                "specifications": specs_list,
            })
        return exported

    @staticmethod
    def _content_terms(text: str) -> set[str]:
        """Strip question filler and product names so retrieval matches the topic."""
        ignored = {
            "a", "about", "an", "and", "are", "can", "could", "do", "does", "for",
            "from", "get", "how", "i", "is", "it", "its", "me", "my", "of", "on",
            "or", "please", "tell", "that", "the", "their", "this", "to", "what", "when",
            "where", "which", "who", "why", "with", "would", "you", "your", "pulse", "buds",
            "nova", "watch", "pro", "google", "play", "gift", "card", "141", "131", "1041",
            "1031", "2001", "p1041", "p1031", "p2001", "features", "feature", "spec", "specs",
            "policy", "clause", "store", "novaretail",
        }
        roots = {"changes": "change", "changed": "change", "changing": "change", "repairs": "repair"}
        return {
            roots.get(word, word)
            for word in re.findall(r"\w+", text.lower())
            if word not in ignored and not word.isdigit()
        }

"""
Deterministic Zero-Cost Template Responder
Complies with Specification Section 9.1, 12, and 13.

Generates localized, fixed responses for simple greetings and standard order status.
Saves token costs and guarantees zero latency for high-frequency queries.
"""

from typing import Literal, Optional, Any


class TemplateResponder:
    """Provides fixed template responses across English, Tamil, and Tanglish."""

    # 1. Greetings
    GREETINGS = {
        "en": (
            "Hello! Welcome to NovaRetail Support. "
            "How can I help you today with your orders, returns, or products?"
        ),
        "ta": (
            "வணக்கம்! நோவாரீடெய்ல் வாடிக்கையாளர் சேவைக்கு வரவேற்கிறோம். "
            "உங்கள் ஆர்டர்கள் அல்லது தயாரிப்புகள் பற்றி எவ்வாறு உதவலாம்?"
        ),
        "tanglish": (
            "Vanakkam! NovaRetail Customer Support-ku welcome. "
            "Ungaloda orders, returns, illa products pathi enna details venum?"
        )
    }

    # 2. Format Order Status
    @classmethod
    def render_order_status(
        cls,
        order_dict: dict[str, Any],
        language: Literal["en", "ta", "tanglish"]
    ) -> str:
        order_id = order_dict["order_id"]
        status = order_dict["status"]
        courier = order_dict.get("courier_name", "Our delivery partner")
        tracking_num = order_dict.get("tracking_number", "")
        item_names = ", ".join([i["name"] for i in order_dict.get("items", [])]) or "items"

        if language == "ta":
            return (
                f"உங்கள் ஆர்டர் **{order_id}** ({item_names}) தற்போது **{status}** நிலையில் உள்ளது.\n"
                f"டெலிவரி நிறுவனம்: {courier} (டிராக்கிங் எண்: {tracking_num})."
            )
        elif language == "tanglish":
            return (
                f"Ungaloda order **{order_id}** ({item_names}) ippo **{status}** status-la irukku.\n"
                f"Courier: {courier} (Tracking: {tracking_num})."
            )
        else:
            return (
                f"Your order **{order_id}** ({item_names}) is currently **{status}**.\n"
                f"Handled by {courier} (Tracking #: {tracking_num})."
            )

    @classmethod
    def get_greeting(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.GREETINGS.get(language, cls.GREETINGS["en"])

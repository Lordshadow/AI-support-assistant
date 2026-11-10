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
                f"### ஆர்டர் நிலை: **{order_id}**\n\n"
                f"- **நிலை:** **{status}**\n"
                f"- **பொருட்கள்:** {item_names}\n"
                f"- **டெலிவரி நிறுவனம்:** {courier} (டிராக்கிங் எண்: `{tracking_num}`)\n\n"
                f"கூடுதல் விவரங்களுக்கு எப்போது வேண்டுமானாலும் கேளுங்கள்!"
            )
        elif language == "tanglish":
            return (
                f"### Order Status: **{order_id}**\n\n"
                f"- **Status:** **{status}**\n"
                f"- **Items:** {item_names}\n"
                f"- **Courier:** {courier} (Tracking: `{tracking_num}`)\n\n"
                f"Edhavadhu help venumna sollunga!"
            )
        else:
            return (
                f"### Order Status: **{order_id}**\n\n"
                f"- **Status:** **{status}**\n"
                f"- **Items:** {item_names}\n"
                f"- **Courier:** {courier} (Tracking #: `{tracking_num}`)\n\n"
                f"Let me know if you would like tracking history, returns, or invoice assistance."
            )

    # 3. Return & Refund Policy (Policy 6.0)
    RETURN_POLICIES = {
        "en": (
            "### NovaRetail Return & Refund Policy (Policy 6.0)\n\n"
            "- **Return Window:** Physical items may be returned within **30 days** of confirmed delivery.\n"
            "- **Condition:** Items must be **unused**, in original packaging with tags, manuals, and accessories intact.\n"
            "- **Refund Timelines:** Approved refunds reflect in **3–5 business days** to your original payment method.\n"
            "- **Digital Goods:** Gift cards and downloadable software are strictly **non-refundable** once delivered.\n"
            "- **Damaged or Defective:** Eligible for **free replacement** or full refund with prepaid return shipping.\n\n"
            "Would you like me to check refund eligibility for a specific order?"
        ),
        "ta": (
            "### நோவாரீடெய்ல் ரிட்டர்ன் & ரீஃபண்ட் பாலிசி (பாலிசி 6.0)\n\n"
            "- **ரிட்டர்ன் காலம்:** டெலிவரி செய்யப்பட்ட நாளிலிருந்து **30 நாட்களுக்குள்** ரிட்டர்ன் செய்யலாம்.\n"
            "- **பொருளின் நிலை:** உபயோகிக்கப்படாமல், அசல் பேக்கிங் மற்றும் ரசீதுடன் இருக்க வேண்டும்.\n"
            "- **ரீஃபண்ட் காலம்:** ஒப்புதல் பெற்ற பின் **3–5 வேலை நாட்களில்** உங்கள் வங்கிக் கணக்கில் வரவு வைக்கப்படும்.\n"
            "- **டிஜிட்டல் பொருட்கள்:** கிஃப்ட் கார்டுகள் மாற்றவோ ரீஃபண்ட் செய்யவோ இயலாது.\n\n"
            "குறிப்பிட்ட ஆர்டருக்கு ரீஃபண்ட் தகுதி பார்க்க வேண்டுமா?"
        ),
        "tanglish": (
            "### NovaRetail Return & Refund Policy (Policy 6.0)\n\n"
            "- **Return Window:** Delivery aanadhula irundhu **30 days-kulla** return pannalam.\n"
            "- **Product Condition:** Use pannama, original packaging and accessories-oda irukkanum.\n"
            "- **Refund Time:** Approval aanadhukku appuram **3–5 business days-la** unga account-la credit aagidum.\n"
            "- **Digital Items:** Gift cards and digital codes non-refundable.\n\n"
            "Edhavadhu specific order-ku refund check panna venduma?"
        )
    }

    # 4. Shipping & Delivery
    SHIPPING_POLICIES = {
        "en": (
            "### Shipping & Delivery Details\n\n"
            "- **Standard Delivery:** **3–5 business days** for major metro cities; 5–7 days for other regions.\n"
            "- **Shipping Charges:** **Free delivery** on all orders above **₹500** ($50). Flat ₹50 for orders below ₹500.\n"
            "- **Courier Partners:** BlueDart Express, Delhivery, and Ekart Logistics.\n"
            "- **Tracking:** A live tracking link is sent via SMS and email as soon as your package ships.\n\n"
            "Provide your Order ID anytime to view live tracking updates."
        ),
        "ta": (
            "### டெலிவரி மற்றும் ஷிப்பிங் விவரங்கள்\n\n"
            "- **டெலிவரி காலம்:** முக்கிய நகரங்களில் **3–5 வேலை நாட்கள்**; பிற பகுதிகளில் 5–7 நாட்கள்.\n"
            "- **டெலிவரி கட்டணம்:** **₹500**க்கு மேற்பட்ட ஆர்டர்களுக்கு **இலவச டெலிவரி**.\n"
            "- **டெலிவரி நிறுவனங்கள்:** BlueDart Express, Delhivery, மற்றும் Ekart Logistics."
        ),
        "tanglish": (
            "### Shipping & Delivery Details\n\n"
            "- **Delivery Time:** Major cities-la **3–5 business days**; other regions-la 5–7 days.\n"
            "- **Shipping Fee:** **₹500-ku mela** free delivery! Adhukku keezha flat ₹50.\n"
            "- **Couriers:** BlueDart, Delhivery, and Ekart Logistics."
        )
    }

    # 5. Payment Methods
    PAYMENT_METHODS = {
        "en": (
            "### Accepted Payment Options\n\n"
            "- **UPI:** Google Pay, PhonePe, Paytm, and all BHIM UPI apps.\n"
            "- **Credit & Debit Cards:** Visa, MasterCard, RuPay, and American Express.\n"
            "- **Net Banking:** Supported across all major national and private banks.\n"
            "- **Cash on Delivery (COD):** Available for orders up to ₹10,000.\n"
            "- **Security:** All transactions are protected with 256-bit bank-grade encryption."
        ),
        "ta": (
            "### ஏற்றுக்கொள்ளப்படும் பணம் செலுத்தும் முறைகள்\n\n"
            "- **UPI:** Google Pay, PhonePe, Paytm.\n"
            "- **கார்டுகள்:** Visa, MasterCard, RuPay கிரெடிட் & டெபிட் கார்டுகள்.\n"
            "- **Cash on Delivery (COD):** ₹10,000 வரையிலான ஆர்டர்களுக்கு கிடைக்கும்."
        ),
        "tanglish": (
            "### Payment Methods\n\n"
            "- **UPI:** Google Pay, PhonePe, Paytm.\n"
            "- **Cards:** Visa, MasterCard, RuPay Credit/Debit cards.\n"
            "- **Cash on Delivery (COD):** ₹10,000 varaikkum COD available."
        )
    }

    # 6. Cancellation Policy
    CANCELLATION_POLICIES = {
        "en": (
            "### Order Cancellation Policy\n\n"
            "- **Cancellation Window:** Orders can be cancelled within **2 hours** of placement while in **Processing** status.\n"
            "- **Shipped Orders:** Once an order is **Shipped**, it cannot be cancelled directly, but you may refuse delivery or request a return within 30 days.\n"
            "- **Refund on Cancellation:** 100% of the purchase amount is credited back within **24–48 hours** to the original payment source."
        ),
        "ta": (
            "### ஆர்டர் ரத்து செய்யும் கொள்கை\n\n"
            "- **ரத்து செய்யும் நேரம்:** ஆர்டர் செய்த **2 மணி நேரத்திற்குள்** ரத்து செய்யலாம்.\n"
            "- **ஷிப் செய்யப்பட்ட பின்:** டெலிவரியை நிராகரிக்கலாம் அல்லது 30 நாட்களுக்குள் ரிட்டர்ன் செய்யலாம்.\n"
            "- **ரீஃபண்ட்:** **24–48 மணி நேரத்தில்** உங்கள் பண வரவு வைக்கப்படும்."
        ),
        "tanglish": (
            "### Order Cancellation Policy\n\n"
            "- **Time Window:** Order pota **2 hours-kulla** cancel pannalam.\n"
            "- **Shipped Orders:** Ship aanadhukku appuram cancel panna mudiyadhu; delivery refuse pannalam.\n"
            "- **Refund:** **24–48 hours-la** full refund unga account-ku vandhudum."
        )
    }

    # 7. Customer Support Hours
    SUPPORT_HOURS = {
        "en": (
            "### NovaRetail Customer Support Hours\n\n"
            "- **AI Virtual Assistant:** Available **24/7** for tracking, policies, and product details.\n"
            "- **Human Executive Team:** Monday – Saturday, **9:00 AM – 8:00 PM IST**.\n"
            "- **Email Support:** `support@novaretail.com` (response within 24 hours).\n"
            "- **Toll-Free Helpline:** 1800-123-NOVA.\n\n"
            "Would you like me to connect you with a live support executive right now?"
        ),
        "ta": (
            "### வாடிக்கையாளர் சேவை நேரம்\n\n"
            "- **AI அசிஸ்டெண்ட்:** **24/7** எப்போதும் கிடைக்கும்.\n"
            "- **நேரடி நிர்வாகிகள்:** திங்கள் – சனி, **காலை 9:00 முதல் இரவு 8:00 மணி வரை**.\n"
            "- **மின்னஞ்சல்:** `support@novaretail.com`"
        ),
        "tanglish": (
            "### Customer Support Timings\n\n"
            "- **AI Assistant:** **24/7** eppovum available.\n"
            "- **Live Executives:** Monday to Saturday, **9:00 AM to 8:00 PM IST**.\n"
            "- **Email:** `support@novaretail.com`"
        )
    }

    @classmethod
    def get_greeting(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.GREETINGS.get(language, cls.GREETINGS["en"])

    @classmethod
    def get_return_policy(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.RETURN_POLICIES.get(language, cls.RETURN_POLICIES["en"])

    @classmethod
    def get_shipping_policy(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.SHIPPING_POLICIES.get(language, cls.SHIPPING_POLICIES["en"])

    @classmethod
    def get_payment_methods(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.PAYMENT_METHODS.get(language, cls.PAYMENT_METHODS["en"])

    @classmethod
    def get_cancellation_policy(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.CANCELLATION_POLICIES.get(language, cls.CANCELLATION_POLICIES["en"])

    @classmethod
    def get_support_hours(cls, language: Literal["en", "ta", "tanglish"]) -> str:
        return cls.SUPPORT_HOURS.get(language, cls.SUPPORT_HOURS["en"])

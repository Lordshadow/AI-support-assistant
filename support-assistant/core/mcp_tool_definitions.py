"""
MCP Tool Definitions and LLM Tool Schemas
Complies with Customer Support Assistant Specification Sections 7 & 15.1.
Enforces that customer_id and auth_level are NEVER model parameters.
"""

from dataclasses import dataclass
from typing import Literal, Any


@dataclass(frozen=True)
class SessionContext:
    tenant_id: str
    conv_id: str
    customer_id: str | None
    level: Literal["anonymous", "identified", "verified"]
    channel: Literal["web", "whatsapp"]


# OpenAI/Groq compatible Function Calling Schema exposed to the LLM
MCP_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_current_page_context",
            "description": "Read the validated page and entity context supplied by the active website session.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # -------------------------------------------------------------
    # 1. CATALOG SERVER (Read-Only)
    # -------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "find_product",
            "description": (
                "Resolve a customer's exact product/model name or colloquial phrasing to canonical product IDs. "
                "Use before product-specific retrieval when the current validated page context does not already identify the exact model; clarify if multiple variants match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name_text": {
                        "type": "string",
                        "description": "Product name or phrase spoken by customer, e.g., 'Pulse Buds 141'."
                    }
                },
                "required": ["name_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_price",
            "description": (
                "Fetch live price, active discount, and real-time stock availability for a resolved product_id. "
                "Never quote prices or stock status without calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The exact product ID resolved from find_product (e.g., 'P1041')."
                    }
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Fetch the complete structured specification record for the exact product ID, including available technical features, dimensions, capacity, materials, and compatibility fields. Use for product questions and never infer missing values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Exact product identifier (e.g., 'P1041')."
                    }
                },
                "required": ["product_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_product_docs",
            "description": "Search the exact product's manuals, FAQs, usage, compatibility, troubleshooting, and other product-specific documentation. Use the customer's actual question as the query; keep retrieval scoped to this product ID. For product questions, use alongside get_product_details when both structured specs and explanatory guidance are useful.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Resolved product ID to confine RAG retrieval."
                    },
                    "question": {
                        "type": "string",
                        "description": "Specific query regarding features, troubleshooting, or usage."
                    }
                },
                "required": ["product_id", "question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": "Search return policy, refund rules, warranty clauses, and delivery guidelines from store policy documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Specific policy question, e.g. 'return window for electronics' or 'digital gift cards'."
                    }
                },
                "required": ["question"]
            }
        }
    },

    # -------------------------------------------------------------
    # 2. ORDER SERVER (Read-Only, Requires Identified Session)
    # -------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Fetch status, item list, expected delivery date, and courier details for a customer's order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The customer's order number, e.g., 'ORD-9842'."
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_orders",
            "description": "List the customer's most recent orders (up to 5) when they ask about their past purchases without an ID.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    # -------------------------------------------------------------
    # 3. REFUND SERVER (State-Changing, Requires Verified Session)
    # -------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "check_refund_eligibility",
            "description": "Check if an order or specific item is eligible for return/refund based on store policy and delivery timestamp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to check."
                    }
                },
                "required": ["order_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_refund_request",
            "description": (
                "Initiate a refund request for an eligible order. "
                "Enforces auto-refund under ₹2,000 and flags amounts over ₹2,000 for senior executive approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID to refund."
                    },
                    "reason": {
                        "type": "string",
                        "description": "Customer stated reason for refund, e.g. 'defective item' or 'not as described'."
                    }
                },
                "required": ["order_id", "reason"]
            }
        }
    },

    # -------------------------------------------------------------
    # 4. HANDOFF SERVER
    # -------------------------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "handoff_to_human",
            "description": "Transfer the conversation to a human support executive when requested or when policy bounds cannot be met.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Concise reason for transfer, e.g., 'customer dispute' or 'explicit human request'."
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief summary of conversation context for the incoming support executive."
                    }
                },
                "required": ["reason", "summary"]
            }
        }
    }
]

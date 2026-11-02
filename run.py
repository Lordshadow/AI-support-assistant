"""
NovaRetail Customer Support Assistant - Application Runner
Starts the Channel Gateway ASGI service with Customer Web Widget & Supervisor Console.
"""

import os
import sys
from pathlib import Path


def load_env_file(env_path: Path):
    """Loads environment variables from .env file without external dependencies."""
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = val


# 1. Load .env from project root
ROOT_DIR = Path(__file__).parent.resolve()
load_env_file(ROOT_DIR / ".env")

# 2. Add support-assistant to sys.path
SUPPORT_ASSISTANT_DIR = ROOT_DIR / "support-assistant"
if str(SUPPORT_ASSISTANT_DIR) not in sys.path:
    sys.path.insert(0, str(SUPPORT_ASSISTANT_DIR))

# 3. Create ASGI application
from services.assistant_api.gateway_app import create_default_app
app = create_default_app()


def print_banner(host: str, port: int, has_groq: bool):
    url_base = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    ai_mode = "🟢 Groq API (Live LLM)" if has_groq else "🟡 Deterministic Mock Engine (Offline Mode - Add GROQ_API_KEY in .env)"

    print("=" * 70)
    print("   🛡️   NOVARETAIL CUSTOMER SUPPORT ASSISTANT   🛡️")
    print("=" * 70)
    print(f" Status:        RUNNING")
    print(f" AI Model Mode: {ai_mode}")
    print(f" Server Port:   {port} (Host: {host})")
    print("-" * 70)
    print(" ACCESS ENDPOINTS:")
    print(f"  💬 Customer Web Chat Widget:      {url_base}/widget")
    print(f"  📊 Support Desk Supervisor Console:{url_base}/desk")
    print(f"  🩺 Health Probe:                  {url_base}/health")
    print(f"  📨 WhatsApp Webhook:              {url_base}/webhooks/whatsapp")
    print("-" * 70)
    print(" Trilingual support: English • தமிழ் (Tamil) • Tanglish")
    print(" Financial policy:   ₹2,000 auto-limit with supervisor review & OTP")
    print("=" * 70)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))
    has_groq = bool(os.getenv("GROQ_API_KEY", "").strip())

    print_banner(host, port, has_groq)

    # Launch Uvicorn ASGI server
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )

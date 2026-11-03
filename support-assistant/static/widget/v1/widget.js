/**
 * NovaRetail Embeddable Customer Support Widget (v1)
 * Complies with Specification Section 16.1 & 16.2.
 *
 * Security & Encapsulation Features:
 * 1. Open Shadow DOM (element.attachShadow({ mode: 'open' })): Full style and DOM isolation.
 * 2. Strict textContent rendering: Zero innerHTML injection prevents DOM XSS.
 * 3. Dynamic Token Refresh: Calls configured data-get-token callback before sending.
 * 4. Context Extraction: Automatically sends data-tenant and data-product-id with each turn.
 */

(function () {
  "use strict";

  // Prevent multiple initializations
  if (document.getElementById("novaretail-support-widget-host")) {
    return;
  }

  // 1. Identify current script tag and configuration
  const currentScript =
    document.currentScript ||
    document.querySelector('script[src*="widget.js"]');

  const tenantId =
    (currentScript && currentScript.getAttribute("data-tenant")) ||
    "tenant_novaretail";
  const productId =
    (currentScript && currentScript.getAttribute("data-product-id")) || null;
  const tokenCallbackName =
    (currentScript && currentScript.getAttribute("data-get-token")) || null;
  const apiBase =
    (currentScript && currentScript.getAttribute("data-api-base")) ||
    (currentScript && currentScript.src ? new URL(currentScript.src).origin : "");

  // 2. Generate or retrieve conversation ID from sessionStorage
  let convId = sessionStorage.getItem("novaretail_conv_id");
  if (!convId) {
    convId = "web_" + Math.random().toString(36).substring(2, 12);
    sessionStorage.setItem("novaretail_conv_id", convId);
  }

  // 3. Create host element and attach Open Shadow Root
  const host = document.createElement("div");
  host.id = "novaretail-support-widget-host";
  document.body.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });

  // 4. Scoped CSS for Shadow DOM
  const styles = `
    :host {
      --primary: #0284c7;
      --primary-dark: #0369a1;
      --bg: #ffffff;
      --surface: #f8fafc;
      --border: #e2e8f0;
      --text: #0f172a;
      --text-muted: #64748b;
      --bot-bubble: #f1f5f9;
      --user-bubble: #0284c7;
      --user-text: #ffffff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      box-sizing: border-box;
      z-index: 2147483647;
      position: fixed;
      bottom: 24px;
      right: 24px;
    }
    *, *::before, *::after {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    /* Launcher Bubble */
    .launcher-btn {
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background: linear-gradient(135deg, var(--primary), var(--primary-dark));
      color: #ffffff;
      border: none;
      box-shadow: 0 10px 25px -5px rgba(2, 132, 199, 0.4), 0 8px 10px -6px rgba(2, 132, 199, 0.2);
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease;
    }
    .launcher-btn:hover {
      transform: scale(1.06);
    }
    .launcher-btn svg {
      width: 28px;
      height: 28px;
      fill: currentColor;
    }
    /* Chat Window Container */
    .chat-window {
      position: absolute;
      bottom: 76px;
      right: 0;
      width: 380px;
      height: 580px;
      max-height: calc(100vh - 120px);
      max-width: calc(100vw - 32px);
      background: var(--bg);
      border-radius: 16px;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.15), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
      border: 1px solid var(--border);
      display: none;
      flex-direction: column;
      overflow: hidden;
      animation: popup 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .chat-window.open {
      display: flex;
    }
    @keyframes popup {
      from { opacity: 0; transform: translateY(16px) scale(0.96); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    /* Header */
    .chat-header {
      background: linear-gradient(135deg, var(--primary), var(--primary-dark));
      color: #ffffff;
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .header-title {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -0.01em;
    }
    .header-status {
      font-size: 12px;
      opacity: 0.9;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 3px;
    }
    .status-dot {
      width: 7px;
      height: 7px;
      background: #4ade80;
      border-radius: 50%;
      box-shadow: 0 0 6px #4ade80;
    }
    .close-btn {
      background: rgba(255, 255, 255, 0.2);
      border: none;
      color: #ffffff;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      transition: background 0.15s;
    }
    .close-btn:hover {
      background: rgba(255, 255, 255, 0.35);
    }
    /* Messages Body */
    .messages-body {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      background: #fafafa;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .msg-row {
      display: flex;
      flex-direction: column;
      max-width: 82%;
    }
    .msg-row.bot {
      align-self: flex-start;
    }
    .msg-row.user {
      align-self: flex-end;
    }
    .bubble {
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 13.5px;
      line-height: 1.45;
      word-break: break-word;
      white-space: pre-wrap;
    }
    .msg-row.bot .bubble {
      background: var(--bot-bubble);
      color: var(--text);
      border: 1px solid var(--border);
      border-top-left-radius: 4px;
    }
    .msg-row.user .bubble {
      background: var(--user-bubble);
      color: var(--user-text);
      border-top-right-radius: 4px;
    }
    .msg-time {
      font-size: 10px;
      color: var(--text-muted);
      margin-top: 4px;
    }
    .msg-row.user .msg-time {
      align-self: flex-end;
    }
    /* Typing Indicator */
    .typing-indicator {
      display: none;
      align-self: flex-start;
      background: var(--bot-bubble);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 8px 14px;
      gap: 4px;
      align-items: center;
    }
    .typing-indicator.active {
      display: flex;
    }
    .dot {
      width: 6px;
      height: 6px;
      background: #94a3b8;
      border-radius: 50%;
      animation: pulse 1.2s infinite;
    }
    .dot:nth-child(2) { animation-delay: 0.2s; }
    .dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes pulse {
      0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
      40% { opacity: 1; transform: scale(1.1); }
    }
    /* Quick Replies */
    .quick-chips {
      display: flex;
      gap: 6px;
      padding: 8px 12px;
      background: #ffffff;
      border-top: 1px solid var(--border);
      overflow-x: auto;
      scrollbar-width: none;
    }
    .quick-chips::-webkit-scrollbar {
      display: none;
    }
    .chip {
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      color: #334155;
      font-size: 11.5px;
      padding: 5px 10px;
      border-radius: 9999px;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s;
    }
    .chip:hover {
      background: #e2e8f0;
      border-color: #94a3b8;
    }
    /* Input Area */
    .input-bar {
      padding: 12px;
      background: #ffffff;
      border-top: 1px solid var(--border);
      display: flex;
      gap: 8px;
    }
    .input-field {
      flex: 1;
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 8px 14px;
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s;
    }
    .input-field:focus {
      border-color: var(--primary);
    }
    .send-btn {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: var(--primary);
      color: #ffffff;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.15s;
    }
    .send-btn:hover {
      background: var(--primary-dark);
    }
    .send-btn svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }
    /* OTP Modal */
    .otp-overlay {
      position: absolute;
      inset: 0;
      background: rgba(15, 23, 42, 0.6);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 20px;
      backdrop-filter: blur(2px);
      z-index: 10;
    }
    .otp-overlay.active {
      display: flex;
    }
    .otp-card {
      background: #ffffff;
      border-radius: 14px;
      padding: 20px;
      width: 100%;
      text-align: center;
      box-shadow: 0 10px 25px rgba(0,0,0,0.2);
    }
    .otp-title {
      font-size: 15px;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 6px;
    }
    .otp-desc {
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 14px;
      line-height: 1.4;
    }
    .otp-input {
      letter-spacing: 6px;
      font-size: 18px;
      font-weight: 700;
      text-align: center;
      width: 70%;
      padding: 8px;
      border: 2px solid var(--border);
      border-radius: 8px;
      outline: none;
      margin-bottom: 14px;
    }
    .otp-input:focus {
      border-color: var(--primary);
    }
    .otp-btn {
      background: var(--primary);
      color: white;
      border: none;
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      width: 100%;
    }
  `;

  // 5. Build DOM Structure safely inside Shadow Root
  const styleEl = document.createElement("style");
  styleEl.textContent = styles;
  shadow.appendChild(styleEl);

  // Launcher Button
  const launcher = document.createElement("button");
  launcher.className = "launcher-btn";
  launcher.setAttribute("aria-label", "Open Customer Support Chat");
  launcher.innerHTML = `
    <svg viewBox="0 0 24 24">
      <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
    </svg>
  `;
  shadow.appendChild(launcher);

  // Chat Window
  const chatWindow = document.createElement("div");
  chatWindow.className = "chat-window";
  chatWindow.innerHTML = `
    <div class="chat-header">
      <div>
        <div class="header-title">NovaRetail Support</div>
        <div class="header-status">
          <span class="status-dot"></span>
          <span>Online | English & Tanglish</span>
        </div>
      </div>
      <button class="close-btn" aria-label="Close Chat">&times;</button>
    </div>
    <div class="messages-body"></div>
    <div class="typing-indicator">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
    </div>
    <div class="quick-chips">
      <button class="chip" data-msg="Track my order">Track Order</button>
      <button class="chip" data-msg="Return & refund policy">Return Policy</button>
      <button class="chip" data-msg="Talk to human agent">Speak with Agent</button>
    </div>
    <div class="input-bar">
      <input type="text" class="input-field" placeholder="Ask a question or enter order ID..." />
      <button class="send-btn" aria-label="Send message">
        <svg viewBox="0 0 24 24">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
        </svg>
      </button>
    </div>
    <div class="otp-overlay">
      <div class="otp-card">
        <div class="otp-title">Security Verification</div>
        <div class="otp-desc">Please enter the 6-digit OTP sent to your registered phone to verify identity.</div>
        <input type="text" class="otp-input" maxlength="6" placeholder="000000" />
        <button class="otp-btn">Verify & Continue</button>
      </div>
    </div>
  `;
  shadow.appendChild(chatWindow);

  const messagesBody = chatWindow.querySelector(".messages-body");
  const typingIndicator = chatWindow.querySelector(".typing-indicator");
  const inputField = chatWindow.querySelector(".input-field");
  const sendBtn = chatWindow.querySelector(".send-btn");
  const closeBtn = chatWindow.querySelector(".close-btn");
  const otpOverlay = chatWindow.querySelector(".otp-overlay");
  const otpInput = chatWindow.querySelector(".otp-input");
  const otpVerifyBtn = chatWindow.querySelector(".otp-btn");

  let activeChallengeId = null;

  // 6. Safe Text Rendering: Zero innerHTML
  function appendMessage(text, isUser = false) {
    const row = document.createElement("div");
    row.className = "msg-row " + (isUser ? "user" : "bot");

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text; // STRICTLY textContent to prevent DOM XSS

    const time = document.createElement("div");
    time.className = "msg-time";
    const now = new Date();
    time.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    row.appendChild(bubble);
    row.appendChild(time);
    messagesBody.appendChild(row);
    messagesBody.scrollTop = messagesBody.scrollHeight;
  }

  // 7. Dynamic Token Retrieval
  async function fetchCustomerToken() {
    if (!tokenCallbackName) return null;
    try {
      // Evaluate function by name safely on window object
      const fn = window[tokenCallbackName];
      if (typeof fn === "function") {
        return await fn();
      }
    } catch (e) {
      console.warn("[NovaRetail Widget] Error invoking token callback:", e);
    }
    return null;
  }

  // 8. Send Turn to Gateway
  async function sendMessage(text) {
    const clean = (text || "").trim();
    if (!clean) return;

    appendMessage(clean, true);
    inputField.value = "";
    typingIndicator.classList.add("active");
    messagesBody.scrollTop = messagesBody.scrollHeight;

    const token = await fetchCustomerToken();

    const headers = {
      "Content-Type": "application/json",
    };
    if (token) {
      headers["Authorization"] = "Bearer " + token;
    }

    const payload = {
      conv_id: convId,
      message: clean,
      channel: "web",
      tenant_id: tenantId,
      product_id: productId,
    };

    try {
      const endpoint = (apiBase ? apiBase : "") + "/chat/messages";
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload),
      });

      typingIndicator.classList.remove("active");

      if (resp.status === 403) {
        appendMessage("Access Denied: This website domain is not authorized to communicate with this assistant instance.");
        return;
      }

      if (!resp.ok) {
        appendMessage("Sorry, I encountered a temporary network issue. Please try again in a moment.");
        return;
      }

      const data = await resp.json();
      if (data.reply) {
        appendMessage(data.reply, false);
      }

      // Check if step-up OTP challenge requested
      if (data.requires_step_up) {
        triggerStepUp();
      }
    } catch (err) {
      typingIndicator.classList.remove("active");
      appendMessage("Network connection error. Please verify your internet connection.");
      console.error("[NovaRetail Widget] Turn request failed:", err);
    }
  }

  async function triggerStepUp() {
    otpOverlay.classList.add("active");
    otpInput.value = "";
    otpInput.focus();

    // Trigger OTP send
    try {
      const endpoint = (apiBase ? apiBase : "") + "/auth/otp/send";
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conv_id: convId,
          destination: "+919876543210",
          tenant_id: tenantId,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        activeChallengeId = data.challenge_id;
      }
    } catch (e) {
      console.warn("[NovaRetail Widget] Failed to request OTP challenge:", e);
    }
  }

  async function verifyStepUp() {
    const code = (otpInput.value || "").trim();
    if (!code || code.length < 4) return;

    try {
      const endpoint = (apiBase ? apiBase : "") + "/auth/otp/verify";
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conv_id: convId,
          challenge_id: activeChallengeId || "ch_default",
          candidate_code: code,
          tenant_id: tenantId,
        }),
      });
      const data = await resp.json();
      if (data.success) {
        otpOverlay.classList.remove("active");
        appendMessage("Verification successful! Processing your refund request now...");
      } else {
        alert(data.message || "Invalid OTP code. Please try again.");
      }
    } catch (e) {
      alert("Verification failed. Please check network connection.");
    }
  }

  // 9. Attach Event Listeners
  launcher.addEventListener("click", () => {
    chatWindow.classList.toggle("open");
    if (chatWindow.classList.contains("open")) {
      inputField.focus();
      if (messagesBody.children.length === 0) {
        appendMessage("Hello! Welcome to NovaRetail. How can I assist you with your orders or product queries today?");
      }
    }
  });

  closeBtn.addEventListener("click", () => {
    chatWindow.classList.remove("open");
  });

  sendBtn.addEventListener("click", () => {
    sendMessage(inputField.value);
  });

  inputField.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      sendMessage(inputField.value);
    }
  });

  // Quick prompt chips
  chatWindow.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const msg = chip.getAttribute("data-msg");
      if (msg) sendMessage(msg);
    });
  });

  // OTP handlers
  otpVerifyBtn.addEventListener("click", verifyStepUp);
  otpInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") verifyStepUp();
  });
})();

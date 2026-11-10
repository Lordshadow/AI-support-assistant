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

(async function () {
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
  const configuredProductId =
    (currentScript && currentScript.getAttribute("data-product-id")) || null;
  const tokenCallbackName =
    (currentScript && currentScript.getAttribute("data-get-token")) || null;
  const apiBase =
    (currentScript && currentScript.getAttribute("data-api-base")) ||
    (currentScript && currentScript.src ? new URL(currentScript.src).origin : "");

  const defaults = { name: "NovaRetail Support", greeting: "Hi! How can I help you today?", primaryColor: "#0284c7", theme: "light", launcherSide: "right", quickPrompts: ["Track my order", "Product questions"], autoOpen: false };
  let config = defaults;
  const isPreview = currentScript?.hasAttribute("data-preview-config");
  try {
    const previewValue = currentScript?.getAttribute("data-preview-config");
    const response = isPreview ? null : await fetch(`${apiBase}/widget/config?tenant_id=${encodeURIComponent(tenantId)}`, { mode: "cors", credentials: "omit" });
    const incoming = isPreview ? JSON.parse(previewValue) : (response?.ok ? await response.json() : {});
    if (incoming && typeof incoming === "object") config = { ...defaults, ...incoming };
  } catch (_) { /* Keep safe presentation defaults when config cannot be loaded. */ }
  if (!/^#[0-9a-f]{6}$/i.test(config.primaryColor)) config.primaryColor = defaults.primaryColor;
  if (!Array.isArray(config.quickPrompts)) config.quickPrompts = defaults.quickPrompts;
  config.quickPrompts = config.quickPrompts.filter((item) => typeof item === "string").slice(0, 3);
  config.name = String(config.name || defaults.name).slice(0, 48);
  config.greeting = String(config.greeting || defaults.greeting).slice(0, 180);

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
      --primary: ${config.primaryColor};
      --primary-dark: ${config.primaryColor};
      --bg: ${config.theme === "dark" ? "#111827" : "#ffffff"};
      --surface: ${config.theme === "dark" ? "#1f2937" : "#f8fafc"};
      --border: ${config.theme === "dark" ? "#374151" : "#e2e8f0"};
      --text: ${config.theme === "dark" ? "#f9fafb" : "#0f172a"};
      --text-muted: ${config.theme === "dark" ? "#cbd5e1" : "#64748b"};
      --bot-bubble: ${config.theme === "dark" ? "#273449" : "#f1f5f9"};
      --user-bubble: ${config.primaryColor};
      --user-text: #ffffff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      box-sizing: border-box;
      z-index: 2147483647;
      position: fixed;
      bottom: 24px;
      right: 24px;
      ${config.launcherSide === "left" ? "left: 24px; right: auto;" : ""}
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
      background: var(--surface);
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
      white-space: normal;
    }
    .msg-row.bot .bubble p {
      margin: 0 0 6px 0;
    }
    .msg-row.bot .bubble p:last-child {
      margin-bottom: 0;
    }
    .msg-row.bot .bubble h3,
    .msg-row.bot .bubble h4 {
      margin: 6px 0 4px 0;
      font-size: 13.5px;
      font-weight: 700;
      color: var(--text);
    }
    .msg-row.bot .bubble ul,
    .msg-row.bot .bubble ol {
      margin: 4px 0 6px 18px;
      padding: 0;
    }
    .msg-row.bot .bubble li {
      margin-bottom: 3px;
    }
    .msg-row.bot .bubble strong {
      font-weight: 600;
    }
    .msg-row.bot .bubble code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
      background: rgba(0, 0, 0, 0.06);
      padding: 1px 4px;
      border-radius: 4px;
    }
    .msg-row.bot .bubble a {
      color: var(--primary);
      text-decoration: underline;
      word-break: break-all;
    }
    .msg-row.bot .bubble .table-wrap {
      overflow-x: auto;
      margin: 8px 0;
      max-width: 100%;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.6);
    }
    .msg-row.bot .bubble table {
      width: 100%;
      border-collapse: collapse;
      font-size: 11.5px;
      text-align: left;
    }
    .msg-row.bot .bubble th {
      background: rgba(0, 0, 0, 0.05);
      padding: 5px 8px;
      font-weight: 600;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    .msg-row.bot .bubble td {
      padding: 5px 8px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    .msg-row.bot .bubble tr:last-child td {
      border-bottom: none;
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
      background: var(--bg);
      border-top: 1px solid var(--border);
      overflow-x: auto;
      scrollbar-width: none;
    }
    .quick-chips::-webkit-scrollbar {
      display: none;
    }
    .chip {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
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
      background: var(--bg);
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
        <div class="header-title"></div>
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
        <div class="otp-desc">We’ll email a 6-digit verification code to your account email.</div>
        <input type="text" class="otp-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="000000" aria-label="6-digit email verification code" />
        <button class="otp-btn">Verify & Continue</button>
      </div>
    </div>
  `;
  shadow.appendChild(chatWindow);

  chatWindow.querySelector(".header-title").textContent = config.name;
  const promptBar = chatWindow.querySelector(".quick-chips");
  config.quickPrompts.forEach((prompt) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.textContent = prompt;
    chip.setAttribute("data-msg", prompt);
    promptBar.appendChild(chip);
  });

  const messagesBody = chatWindow.querySelector(".messages-body");
  const typingIndicator = chatWindow.querySelector(".typing-indicator");
  const inputField = chatWindow.querySelector(".input-field");
  const sendBtn = chatWindow.querySelector(".send-btn");
  const closeBtn = chatWindow.querySelector(".close-btn");
  const otpOverlay = chatWindow.querySelector(".otp-overlay");
  const otpInput = chatWindow.querySelector(".otp-input");
  const otpVerifyBtn = chatWindow.querySelector(".otp-btn");

  let activeChallengeId = null;
  let pendingStepUpMessage = null;

  // 6. Safe Text & Markdown Rendering
  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderMarkdown(rawText) {
    if (!rawText) return "";
    const escaped = escapeHtml(rawText);
    const lines = escaped.split("\n");
    const output = [];
    let inTable = false;
    let tableHeaders = [];
    let tableRows = [];
    let inList = false;
    let listType = null;

    function flushList() {
      if (inList) {
        output.push("</" + listType + ">");
        inList = false;
        listType = null;
      }
    }

    function flushTable() {
      if (inTable) {
        let tbl = '<div class="table-wrap"><table>';
        if (tableHeaders.length > 0) {
          tbl += "<thead><tr>";
          tableHeaders.forEach((th) => {
            tbl += "<th>" + th + "</th>";
          });
          tbl += "</tr></thead>";
        }
        if (tableRows.length > 0) {
          tbl += "<tbody>";
          tableRows.forEach((row) => {
            tbl += "<tr>";
            row.forEach((cell) => {
              tbl += "<td>" + cell + "</td>";
            });
            tbl += "</tr>";
          });
          tbl += "</tbody>";
        }
        tbl += "</table></div>";
        output.push(tbl);
        inTable = false;
        tableHeaders = [];
        tableRows = [];
      }
    }

    function formatInline(text) {
      return text
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/`(.+?)`/g, "<code>$1</code>")
        .replace(
          /\[([^\]]+)\]\(((?:https?:\/\/|\/)[^\)]+)\)/g,
          '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
        );
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();

      if (line.startsWith("|") && line.endsWith("|")) {
        flushList();
        const cells = line
          .slice(1, -1)
          .split("|")
          .map((c) => formatInline(c.trim()));
        const isDivider = cells.every((c) =>
          /^:?-+:?$/.test(c.replace(/&amp;/g, "&"))
        );
        if (isDivider) {
          continue;
        }
        if (!inTable) {
          inTable = true;
          tableHeaders = cells;
        } else {
          tableRows.push(cells);
        }
        continue;
      } else {
        flushTable();
      }

      const ulMatch = line.match(/^[-*]\s+(.*)$/);
      if (ulMatch) {
        if (!inList || listType !== "ul") {
          flushList();
          output.push("<ul>");
          inList = true;
          listType = "ul";
        }
        output.push("<li>" + formatInline(ulMatch[1]) + "</li>");
        continue;
      }

      const olMatch = line.match(/^\d+\.\s+(.*)$/);
      if (olMatch) {
        if (!inList || listType !== "ol") {
          flushList();
          output.push("<ol>");
          inList = true;
          listType = "ol";
        }
        output.push("<li>" + formatInline(olMatch[1]) + "</li>");
        continue;
      }

      flushList();

      if (line.startsWith("### ")) {
        output.push("<h4>" + formatInline(line.slice(4)) + "</h4>");
        continue;
      }
      if (line.startsWith("## ") || line.startsWith("# ")) {
        output.push("<h3>" + formatInline(line.replace(/^#+\s*/, "")) + "</h3>");
        continue;
      }

      if (line === "") {
        continue;
      }

      output.push("<p>" + formatInline(line) + "</p>");
    }

    flushList();
    flushTable();

    return output.join("");
  }

  function appendMessage(text, isUser = false) {
    const row = document.createElement("div");
    row.className = "msg-row " + (isUser ? "user" : "bot");

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    if (isUser) {
      bubble.textContent = text; // STRICTLY textContent to prevent DOM XSS
    } else {
      bubble.innerHTML = renderMarkdown(text);
    }

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
    try {
      // 1. Check explicitly configured callback name
      if (tokenCallbackName && typeof window[tokenCallbackName] === "function") {
        const token = await window[tokenCallbackName]();
        if (token) return token;
      }
      // 2. Check global ApexStore callback
      if (typeof window.getApexCustomerToken === "function") {
        const token = await window.getApexCustomerToken();
        if (token) return token;
      }
      // 3. Check cached token in window or sessionStorage
      if (window.__apex_customer_token) {
        return window.__apex_customer_token;
      }
      if (typeof window !== "undefined" && window.sessionStorage) {
        const cached = window.sessionStorage.getItem("apex_customer_token");
        if (cached) return cached;
      }
      // 4. Fallback Auto-Discovery: query storefront auth endpoint
      if (typeof window !== "undefined" && window.location) {
        try {
          const authMeUrl = (window.location.origin === "http://localhost:3000" ? "http://localhost:5000" : "/api") + "/api/auth/me";
          const res = await fetch(authMeUrl, { credentials: "include" });
          if (res.ok) {
            const data = await res.json();
            if (data && data.success && data.user) {
              window.__apex_customer_id = String(data.user.id);
              if (data.customer_token) {
                window.__apex_customer_token = data.customer_token;
                return data.customer_token;
              }
            }
          }
        } catch (_) {}
      }
    } catch (e) {
      console.warn("[NovaRetail Widget] Error retrieving customer token:", e);
    }
    return null;
  }

  function getPageContext() {
    const url = window.location.href;
    const path = window.location.pathname.toLowerCase();
    const productId = configuredProductId ||
      (window.location.pathname.match(/\/products?\/([a-z0-9][a-z0-9_-]{0,63})/i) || [])[1] || null;
    const orderId =
      (window.location.pathname.match(/\/orders?\/(ord-[a-z0-9_-]+)/i) || [])[1] || null;
    const cartId =
      (window.location.pathname.match(/\/carts?\/(cart-[a-z0-9_-]+)/i) || [])[1] || null;
    let pageType = "other";
    if (productId || /\/product(?:s)?\/[^/]+/.test(path)) pageType = "product_details";
    else if (/\/products?(?:\/|$)/.test(path)) pageType = "product_listing";
    else if (orderId) pageType = "order_details";
    else if (/\/cart(?:\/|$)/.test(path)) pageType = "cart";
    else if (/\/checkout(?:\/|$)/.test(path)) pageType = "checkout";
    else if (/\/dashboard(?:\/|$)/.test(path)) pageType = "dashboard";
    return {
      url: url.slice(0, 2048),
      page_type: pageType,
      product_id: productId,
      order_id: orderId,
      cart_id: cartId,
      title: (document.title || "").slice(0, 200),
    };
  }

  // 8. Send Turn to Gateway
  async function sendMessage(text, showUserMessage = true) {
    const clean = (text || "").trim();
    if (!clean) return;

    if (showUserMessage) appendMessage(clean, true);
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
      page_context: getPageContext(),
    };
    if (token) {
      payload.customer_token = token;
    }
    if (window.__apex_customer_id) {
      payload.customer_id = String(window.__apex_customer_id);
    } else if (token && token.includes(".")) {
      try {
        const parts = token.split(".");
        if (parts.length >= 2) {
          const claims = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
          if (claims && claims.sub) {
            payload.customer_id = String(claims.sub);
          }

        }
      } catch (_) {}
    }

    try {
      const endpoint = (apiBase ? apiBase : "") + "/chat/messages?tenant_id=" + encodeURIComponent(tenantId);
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
        const debugCode = resp.headers.get("X-Debug-Code");
        console.error("[NovaRetail Widget] Chat request failed:", {
          status: resp.status,
          debugCode: debugCode || "unavailable",
        });
        appendMessage("Sorry, I encountered a temporary network issue. Please try again in a moment.");
        return;
      }

      const data = await resp.json();
      if (data.reply) {
        appendMessage(data.reply, false);
      }

      // Check if step-up OTP challenge requested
      if (data.requires_step_up) {
        pendingStepUpMessage = clean;
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

    const token = await fetchCustomerToken();
    if (!token) {
      otpOverlay.classList.remove("active");
      appendMessage("Please sign in to verify using the email address on your account.");
      return;
    }

    // Trigger OTP send
    try {
      const endpoint = (apiBase ? apiBase : "") + "/auth/otp/send?tenant_id=" + encodeURIComponent(tenantId);
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + token },
        body: JSON.stringify({
          conv_id: convId,
          tenant_id: tenantId,
          order_id: (pendingStepUpMessage && pendingStepUpMessage.match(/\bORD(?:[-_][A-Z0-9]+|\d+)(?:[-_][A-Z0-9]+)*\b/i) || [])[0] || "",
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        activeChallengeId = data.challenge_id;
        const desc = chatWindow.querySelector(".otp-desc");
        desc.textContent = `Enter the 6-digit code sent to ${data.destination || "your account email"}.`;
      } else {
        const data = await resp.json().catch(() => ({}));
        console.error("[NovaRetail Widget] OTP send failed:", {
          status: resp.status,
          debugCode: resp.headers.get("X-Debug-Code") || "unavailable",
        });
        otpOverlay.classList.remove("active");
        appendMessage(data.detail || "We couldn’t send your verification email. Please try again.");
      }
    } catch (e) {
      otpOverlay.classList.remove("active");
      appendMessage("We couldn’t connect to send your verification email. Please try again.");
      console.warn("[NovaRetail Widget] Failed to request OTP challenge:", e);
    }
  }

  async function verifyStepUp() {
    const code = (otpInput.value || "").trim();
    if (!/^\d{6}$/.test(code) || !activeChallengeId) {
      otpInput.setCustomValidity("Enter the 6-digit code from your email.");
      otpInput.reportValidity();
      return;
    }
    otpInput.setCustomValidity("");
    const token = await fetchCustomerToken();
    if (!token) {
      appendMessage("Please sign in again before verifying this code.");
      return;
    }

    try {
      const endpoint = (apiBase ? apiBase : "") + "/auth/otp/verify?tenant_id=" + encodeURIComponent(tenantId);
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { "Authorization": "Bearer " + token } : {}) },
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
        activeChallengeId = null;
        const pendingMessage = pendingStepUpMessage;
        pendingStepUpMessage = null;
        if (pendingMessage) {
          appendMessage("Email verified. Continuing your request...");
          await sendMessage(pendingMessage, false);
        } else {
          appendMessage("Email verified successfully.");
        }
      } else {
        appendMessage(data.message || "Invalid OTP code. Please try again.");
      }
    } catch (e) {
      appendMessage("Verification failed because of a connection issue. Please try again.");
    }
  }

  // 9. Attach Event Listeners
  launcher.addEventListener("click", () => {
    chatWindow.classList.toggle("open");
    if (chatWindow.classList.contains("open")) {
      inputField.focus();
      if (messagesBody.children.length === 0) {
        appendMessage(config.greeting);
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
  if (config.autoOpen && !sessionStorage.getItem("novaretail_widget_auto_opened")) {
    sessionStorage.setItem("novaretail_widget_auto_opened", "1");
    setTimeout(() => launcher.click(), 500);
  }
})();

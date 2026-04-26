// Tiny chat client. Talks to the BFF at the same origin.
// Streams assistant tokens via SSE; persists everything via the BFF.

const $ = (sel) => document.querySelector(sel);

marked.setOptions({
  breaks: true,
  gfm: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang }).value; } catch {}
    }
    return hljs.highlightAuto(code).value;
  },
});

const state = {
  chatId: null,
  busy: false,
};

// ----------------------------- helpers -----------------------------
function fmtTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function renderMarkdown(text) {
  return marked.parse(text || "");
}

// ----------------------------- chat list -----------------------------
async function loadChats() {
  const res = await fetch("/api/chats");
  if (!res.ok) return;
  const chats = await res.json();
  const list = $("#chat-list");
  list.innerHTML = "";

  // If the user is in a chat that has no persisted messages yet, surface it
  // at the top as a "draft" so they can SEE which chat they're in. Otherwise
  // the very first message would seem to "create a new chat" out of nowhere.
  const currentInList = chats.some((c) => c.chat_id === state.chatId);
  if (state.chatId && !currentInList) {
    list.appendChild(el("li",
      {
        class: "chat-item draft active",
        title: state.chatId,
      },
      el("div", { class: "preview" }, "New chat — type to start"),
      el("div", { class: "meta" },
        el("span", {}, "draft"),
        el("span", {}, fmtTime(new Date().toISOString())),
      ),
    ));
  }

  for (const c of chats) {
    const item = el("li",
      {
        class: "chat-item" + (c.chat_id === state.chatId ? " active" : ""),
        onclick: () => selectChat(c.chat_id),
      },
      el("div", { class: "preview" }, c.last_preview || "(empty)"),
      el("div", { class: "meta" },
        el("span", {}, `${c.message_count} msg`),
        el("span", {}, fmtTime(c.last_at)),
      ),
    );
    list.appendChild(item);
  }
  if (!chats.length && !state.chatId) {
    list.appendChild(el("div", { class: "health" }, "No chats yet — start one."));
  }
}

// ----------------------------- conversation -----------------------------
async function selectChat(chatId) {
  state.chatId = chatId;
  $("#conv-title").textContent = "Chat";
  $("#conv-sub").textContent = chatId;
  $("#conv-meta").textContent = `chat_id: ${chatId}`;
  await loadChats();
  await loadMessages();
}

async function loadMessages() {
  if (!state.chatId) return;
  const res = await fetch(`/api/chats/${state.chatId}/messages`);
  if (!res.ok) return;
  const msgs = await res.json();
  const box = $("#messages");
  box.innerHTML = "";
  if (!msgs.length) {
    box.appendChild(el("div", { class: "empty" },
      el("h2", {}, "Empty chat"),
      el("p", {}, "Send the first message below."),
    ));
    return;
  }
  for (const m of msgs) renderMessage(m);
  scrollToBottom();
}

function renderMessage(m, opts = {}) {
  const box = $("#messages");
  // remove .empty placeholder if present
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();

  const isUser = m.role === "user";
  const bubble = el("div", {
    class: "bubble",
    html: renderMarkdown(m.content || ""),
  });

  const metaChildren = [el("span", {}, fmtTime(m.sent_at || new Date().toISOString()))];
  if (!isUser && m.message_id) {
    const up = el("button", { class: "rate-btn", title: "thumbs up" }, "👍");
    const down = el("button", { class: "rate-btn", title: "thumbs down" }, "👎");
    if (m.rating === true) up.classList.add("active");
    if (m.rating === false) down.classList.add("active");
    up.addEventListener("click", () => rateMessage(m.message_id, true, up, down));
    down.addEventListener("click", () => rateMessage(m.message_id, false, up, down));
    metaChildren.push(up, down);
  }

  const wrapper = el("div", { class: `message ${isUser ? "user" : "ai"}` },
    el("div", { class: "avatar" }, isUser ? "U" : "AI"),
    el("div", {},
      bubble,
      el("div", { class: "meta-line" }, ...metaChildren),
    ),
  );

  if (opts.id) wrapper.dataset.id = opts.id;
  box.appendChild(wrapper);
  return { wrapper, bubble };
}

function scrollToBottom() {
  const box = $("#messages");
  box.scrollTop = box.scrollHeight;
}

async function rateMessage(messageId, value, upBtn, downBtn) {
  const res = await fetch(`/api/messages/${messageId}/rating?rating=${value}`, {
    method: "POST",
  });
  if (!res.ok) return;
  upBtn.classList.toggle("active", value === true);
  downBtn.classList.toggle("active", value === false);
}

// ----------------------------- send / stream -----------------------------
async function sendMessage(text) {
  if (state.busy) return;
  if (!state.chatId) await newChat();

  state.busy = true;
  $("#send").disabled = true;
  $("#input").value = "";

  // Optimistic user bubble.
  renderMessage({ role: "user", content: text });

  // Placeholder AI bubble that we fill as tokens arrive.
  const aiPlaceholder = renderMessage(
    { role: "ai", content: "" },
    { id: "streaming" },
  );
  const cursor = el("span", { class: "cursor" });
  aiPlaceholder.bubble.appendChild(cursor);
  let acc = "";
  scrollToBottom();

  try {
    const res = await fetch(`/api/chats/${state.chatId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text }),
    });
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      // Normalise CRLF → LF: SSE-Starlette emits \r\n\r\n between frames per spec,
      // but our parser uses \n\n. Without this we never find a frame boundary.
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const event = parseSseFrame(frame);
        handleEvent(event, aiPlaceholder, (chunk) => {
          acc += chunk;
          aiPlaceholder.bubble.innerHTML = renderMarkdown(acc);
          aiPlaceholder.bubble.appendChild(cursor);
          scrollToBottom();
        });
      }
    }
  } catch (err) {
    aiPlaceholder.bubble.innerHTML = `<span style="color: var(--error)">Error: ${err.message}</span>`;
  } finally {
    cursor.remove();
    state.busy = false;
    $("#send").disabled = false;
    await loadChats();
  }
}

function parseSseFrame(frame) {
  const out = { event: "message", data: "" };
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) out.event = line.slice(6).trim();
    else if (line.startsWith("data:")) out.data += line.slice(5).trim();
  }
  return out;
}

function handleEvent(ev, ai, onToken) {
  if (!ev.data) return;
  let payload = {};
  try { payload = JSON.parse(ev.data); } catch { return; }
  if (ev.event === "token" && payload.fragment) onToken(payload.fragment);
  if (ev.event === "ai_message" && payload.message_id) {
    ai.wrapper.dataset.id = payload.message_id;
    // Re-render the meta line with the proper message id so 👍/👎 work.
    const meta = ai.wrapper.querySelector(".meta-line");
    if (meta) {
      meta.innerHTML = "";
      meta.appendChild(el("span", {}, fmtTime(payload.sent_at)));
      const up = el("button", { class: "rate-btn" }, "👍");
      const down = el("button", { class: "rate-btn" }, "👎");
      up.addEventListener("click", () => rateMessage(payload.message_id, true, up, down));
      down.addEventListener("click", () => rateMessage(payload.message_id, false, up, down));
      meta.append(up, down);
    }
  }
  if (ev.event === "error" && payload.message) {
    ai.bubble.innerHTML = `<span style="color: var(--error)">Error: ${payload.message}</span>`;
  }
}

// ----------------------------- new chat / health -----------------------------
async function newChat() {
  const res = await fetch("/api/chats", { method: "POST" });
  const { chat_id } = await res.json();
  state.chatId = chat_id;
  $("#conv-title").textContent = "New chat";
  $("#conv-sub").textContent = chat_id;
  $("#conv-meta").textContent = `chat_id: ${chat_id}`;
  $("#messages").innerHTML = "";
  $("#messages").appendChild(el("div", { class: "empty" },
    el("h2", {}, "Say hi 👋"),
    el("p", {}, "Type below to send the first message."),
  ));
  await loadChats();
}

async function refreshHealth() {
  const badge = $("#health");
  try {
    const res = await fetch("/api/health");
    const h = await res.json();
    if (h.ollama_up && h.model_ready) {
      badge.className = "health ok";
      badge.textContent = `● ready · ${h.model}`;
    } else if (h.ollama_up) {
      badge.className = "health bad";
      badge.textContent = `● ollama up, model "${h.model}" not pulled yet`;
    } else {
      badge.className = "health bad";
      badge.textContent = "● ollama unreachable";
    }
  } catch {
    badge.className = "health bad";
    badge.textContent = "● BFF unreachable";
  }
}

// ----------------------------- wiring -----------------------------
$("#new-chat").addEventListener("click", newChat);

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#input").value.trim();
  if (!text) return;
  await sendMessage(text);
});

$("#input").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    $("#composer").requestSubmit();
  }
});

(async function boot() {
  await refreshHealth();
  setInterval(refreshHealth, 15000);
  await loadChats();
  await newChat();
})();

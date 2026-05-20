const chatLog = document.getElementById("chat-log");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const template = document.getElementById("message-template");
const history = [];


function appendMessage(role, text) {
  const node = template.content.firstElementChild.cloneNode(true);
  const isUser = role === "You";
  node.classList.add(isUser ? "message-user" : "message-assistant");
  node.querySelector(".role").textContent = role;
  node.querySelector(".body").textContent = text;
  chatLog.appendChild(node);
  chatLog.scrollTop = chatLog.scrollHeight;
}


function setBusy(busy) {
  const button = chatForm.querySelector("button");
  button.disabled = busy;
  button.textContent = busy ? "Working..." : "Ask Gemma";
}


appendMessage(
  "Assistant",
  "Ask a legal question in plain language. I will use the local Indian law corpus when relevant and explain the answer simply."
);


chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatInput.value.trim();
  if (!message) {
    return;
  }

  appendMessage("You", message);
  const requestHistory = [...history];
  chatInput.value = "";
  setBusy(true);

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: requestHistory }),
    });

    appendMessage("Assistant", data.reply);
    history.push({ role: "user", content: message });
    history.push({ role: "assistant", content: data.reply });
  } catch (error) {
    appendMessage("Assistant", `Error: ${error.message}`);
  } finally {
    setBusy(false);
  }
});

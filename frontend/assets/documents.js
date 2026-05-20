let currentDocumentId = null;

const uploadSection = document.getElementById("upload-section");
const processingSection = document.getElementById("processing-section");
const resultsSection = document.getElementById("results-section");

const dropZone = document.getElementById("drop-zone");
const dzIdle = document.getElementById("dz-idle");
const dzReady = document.getElementById("dz-ready");
const dzFilename = document.getElementById("dz-filename");
const dzClear = document.getElementById("dz-clear");
const scanFileInput = document.getElementById("scan-file");
const scanQuestion = document.getElementById("scan-question");
const analyzeBtn = document.getElementById("analyze-btn");

const resultFilename = document.getElementById("result-filename");
const resultPagesBadge = document.getElementById("result-pages-badge");
const resultTime = document.getElementById("result-time");
const newScanBtn = document.getElementById("new-scan-btn");

const tabBtns = document.querySelectorAll(".tab-btn");
const tabAnalysis = document.getElementById("tab-analysis");
const tabAsk = document.getElementById("tab-ask");
const tabPreviews = document.getElementById("tab-previews");
const analysisOutput = document.getElementById("analysis-output");

const askLog = document.getElementById("ask-log");
const askEmptyState = document.getElementById("ask-empty-state");
const askForm = document.getElementById("ask-form");
const askInput = document.getElementById("ask-input");
const askSubmitBtn = document.getElementById("ask-submit-btn");

const scanPreviews = document.getElementById("scan-previews");
const previewNote = document.getElementById("preview-note");

document.querySelectorAll(".prompt-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    scanQuestion.value = chip.dataset.prompt || "";
    scanQuestion.focus();
  });
});

dropZone.addEventListener("click", (e) => {
  if (!e.target.closest(".dz-clear")) scanFileInput.click();
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) setFile(file);
});

scanFileInput.addEventListener("change", () => {
  if (scanFileInput.files[0]) setFile(scanFileInput.files[0]);
});

dzClear.addEventListener("click", (e) => {
  e.stopPropagation();
  clearFile();
});

function setFile(file) {
  dzIdle.classList.add("hidden");
  dzReady.classList.remove("hidden");
  dzFilename.textContent = file.name;
  dropZone.classList.add("has-file");
  analyzeBtn.disabled = false;

  if (!scanFileInput.files.length || scanFileInput.files[0] !== file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    scanFileInput.files = dt.files;
  }
}

function clearFile() {
  scanFileInput.value = "";
  dzIdle.classList.remove("hidden");
  dzReady.classList.add("hidden");
  dzFilename.textContent = "";
  dropZone.classList.remove("has-file");
  analyzeBtn.disabled = true;
}

analyzeBtn.addEventListener("click", async () => {
  if (!scanFileInput.files.length) return;

  showSection("processing");

  try {
    const formData = new FormData();
    formData.append("document", scanFileInput.files[0]);
    formData.append(
      "question",
      scanQuestion.value.trim() || "Check this document for harmful clauses and explain it simply."
    );

    const data = await fetchJson("/api/scan", { method: "POST", body: formData });

    currentDocumentId = data.documentId || null;

    resultFilename.textContent = data.fileName || "Document";
    resultPagesBadge.textContent = `${data.pagesAnalyzed} pages · ${data.chunkCount} sections`;
    resultTime.textContent = data.processingTime;

    analysisOutput.innerHTML = buildStructuredHtml(data.summary || "");

    scanPreviews.innerHTML = "";
    for (const preview of data.pagePreviews || []) {
      const figure = document.createElement("figure");
      const img = document.createElement("img");
      const caption = document.createElement("figcaption");
      img.src = preview.imageDataUrl;
      img.alt = `Page ${preview.pageNumber}`;
      caption.textContent = `Page ${preview.pageNumber}`;
      figure.append(img, caption);
      scanPreviews.appendChild(figure);
    }

    const previewCount = (data.pagePreviews || []).length;
    const total = data.totalPages || previewCount;
    previewNote.textContent =
      previewCount < total
        ? `Previews for pages 1–${previewCount} of ${total}. Analysis used full text from all pages.`
        : `All ${total} pages included in the review.`;

    askLog.innerHTML = "";
    askLog.appendChild(askEmptyState);
    askEmptyState.classList.remove("hidden");

    activateTab("analysis");
    showSection("results");
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showSection("upload");
    alert(`Error: ${err.message}`);
  }
});

function showSection(which) {
  uploadSection.classList.toggle("hidden", which !== "upload");
  processingSection.classList.toggle("hidden", which !== "processing");
  resultsSection.classList.toggle("hidden", which !== "results");
}

newScanBtn.addEventListener("click", () => {
  currentDocumentId = null;
  clearFile();
  scanQuestion.value = "";
  showSection("upload");
  uploadSection.scrollIntoView({ behavior: "smooth" });
});

tabBtns.forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

function activateTab(tab) {
  tabBtns.forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  tabAnalysis.classList.toggle("hidden", tab !== "analysis");
  tabAsk.classList.toggle("hidden", tab !== "ask");
  tabPreviews.classList.toggle("hidden", tab !== "previews");
}

askForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = askInput.value.trim();
  if (!question || !currentDocumentId) return;

  askEmptyState.classList.add("hidden");
  addAskBubble("You", question);
  askInput.value = "";
  askSubmitBtn.disabled = true;
  askSubmitBtn.textContent = "Asking…";

  const thinkingBubble = addAskBubble("Legal Buddy", "…");

  try {
    const data = await fetchJson("/api/document-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: currentDocumentId, question }),
    });
    thinkingBubble.querySelector(".ask-bubble-body").textContent = data.answer || "No answer returned.";
  } catch (err) {
    thinkingBubble.querySelector(".ask-bubble-body").textContent = `Error: ${err.message}`;
  } finally {
    askSubmitBtn.disabled = false;
    askSubmitBtn.textContent = "Ask";
  }
});

function addAskBubble(role, text) {
  const isUser = role === "You";
  const bubble = document.createElement("div");
  bubble.className = `ask-bubble ${isUser ? "user-bubble" : "ai-bubble"}`;
  bubble.innerHTML = `
    <div class="ask-bubble-role">${escapeHtml(role)}</div>
    <div class="ask-bubble-body">${escapeHtml(text)}</div>
  `;
  askLog.appendChild(bubble);
  askLog.scrollTop = askLog.scrollHeight;
  return bubble;
}

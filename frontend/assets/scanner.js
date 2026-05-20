const scanForm = document.getElementById("scan-form");
const scanFile = document.getElementById("scan-file");
const scanQuestion = document.getElementById("scan-question");
const scanMeta = document.getElementById("scan-meta");
const scanOutput = document.getElementById("scan-output");
const scanPreviews = document.getElementById("scan-previews");

function setBusy(busy) {
  const button = scanForm.querySelector("button");
  button.disabled = busy;
  button.textContent = busy ? "Analyzing..." : "Analyze Document";
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function parseMarkdownBlocks(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];
  let listType = null;

  function flushParagraph() {
    if (!paragraphLines.length) {
      return;
    }
    blocks.push({ type: "paragraph", text: paragraphLines.join(" ").trim() });
    paragraphLines = [];
  }

  function flushList() {
    if (!listItems.length) {
      return;
    }
    blocks.push({ type: listType, items: [...listItems] });
    listItems = [];
    listType = null;
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2].trim(),
      });
      continue;
    }

    const unorderedMatch = line.match(/^[-*]\s+(.*)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listType && listType !== "ul") {
        flushList();
      }
      listType = "ul";
      listItems.push(unorderedMatch[1].trim());
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== "ol") {
        flushList();
      }
      listType = "ol";
      listItems.push(orderedMatch[1].trim());
      continue;
    }

    if (/^[A-Za-z][A-Za-z\s/&,-]{2,60}:$/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: 3, text: line.slice(0, -1).trim() });
      continue;
    }

    if (/^\*\*.+\*\*:$/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: 3, text: line.replace(/^\*\*|\*\*:$|\*\*$/g, "").trim() });
      continue;
    }

    flushList();
    paragraphLines.push(line);
  }

  flushParagraph();
  flushList();
  return blocks;
}

function buildStructuredHtml(markdown) {
  const blocks = parseMarkdownBlocks(markdown);
  const sections = [];
  let currentSection = null;

  function ensureSection() {
    if (!currentSection) {
      currentSection = { title: "Review Summary", body: [] };
      sections.push(currentSection);
    }
  }

  for (const block of blocks) {
    if (block.type === "heading") {
      currentSection = { title: block.text, body: [] };
      sections.push(currentSection);
      continue;
    }

    ensureSection();
    currentSection.body.push(block);
  }

  if (!sections.length) {
    return `
      <div class="scan-review">
        <section class="scan-section">
          <div class="scan-section-body">
            <p>No analysis was returned.</p>
          </div>
        </section>
      </div>
    `;
  }

  const hero = sections[0];
  const heroBody = hero.body.map(renderBlock).join("");
  const detailSections = sections.slice(1)
    .map((section) => `
      <section class="scan-section">
        <div class="scan-section-kicker">Section</div>
        <h3>${renderInlineMarkdown(section.title)}</h3>
        <div class="scan-section-body">
          ${section.body.map(renderBlock).join("") || "<p>No additional details.</p>"}
        </div>
      </section>
    `)
    .join("");

  return `
    <div class="scan-review">
      <section class="scan-hero">
        <div class="scan-section-kicker">AI Review</div>
        <h3>${renderInlineMarkdown(hero.title)}</h3>
        <div class="scan-section-body">
          ${heroBody || "<p>No additional details.</p>"}
        </div>
      </section>
      ${detailSections}
    </div>
  `;
}

function renderBlock(block) {
  if (block.type === "paragraph") {
    return `<p>${renderInlineMarkdown(block.text)}</p>`;
  }

  if (block.type === "ul" || block.type === "ol") {
    const tag = block.type;
    const items = block.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("");
    return `<${tag} class="scan-list">${items}</${tag}>`;
  }

  return "";
}

function showAnalysis(summary) {
  scanOutput.innerHTML = buildStructuredHtml(summary);
}

scanForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!scanFile.files.length) {
    scanMeta.textContent = "Choose a PDF or image first.";
    return;
  }

  setBusy(true);
  scanMeta.textContent = "";
  scanOutput.innerHTML = "";
  scanPreviews.innerHTML = "";

  try {
    const formData = new FormData();
    formData.append("document", scanFile.files[0]);
    formData.append(
      "question",
      scanQuestion.value.trim() || "Check this document for harmful clauses and explain it simply."
    );

    const data = await fetchJson("/api/scan", {
      method: "POST",
      body: formData,
    });

    scanMeta.textContent = `Analyzed ${data.pagesAnalyzed}/${data.totalPages} page(s) with ${data.model} in ${data.processingTime}.`;
    showAnalysis(data.summary || "");

    for (const preview of data.pagePreviews || []) {
      const figure = document.createElement("figure");
      const image = document.createElement("img");
      const caption = document.createElement("figcaption");
      image.src = preview.imageDataUrl;
      image.alt = `Document preview page ${preview.pageNumber}`;
      caption.textContent = `Page ${preview.pageNumber}`;
      figure.append(image, caption);
      scanPreviews.appendChild(figure);
    }
  } catch (error) {
    scanMeta.textContent = `Error: ${error.message}`;
  } finally {
    setBusy(false);
  }
});

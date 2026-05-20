/* Shared markdown → structured HTML for document analysis */

function escapeHtml(v) {
  return String(v)
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

const SECTION_CLASS = {
  risk: ["risk", "red flag", "concern", "warning", "danger", "issue"],
  warning: ["obligation", "important", "dates", "money", "fees", "penalty", "penalties", "financial"],
  action: ["next", "should do", "action", "recommend"],
  safe: ["standard", "common", "looks safe", "normal"],
};

function sectionAccentClass(title) {
  const lower = title.toLowerCase();
  for (const [cls, keywords] of Object.entries(SECTION_CLASS)) {
    if (keywords.some((k) => lower.includes(k))) return `scan-section--${cls}`;
  }
  return "";
}

function sectionKicker(accent) {
  if (accent.includes("risk")) return "Red flags";
  if (accent.includes("warning")) return "Obligations";
  if (accent.includes("action")) return "Next steps";
  if (accent.includes("safe")) return "Standard terms";
  return "Section";
}

function parseMarkdownBlocks(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paraLines = [];
  let listItems = [];
  let listType = null;

  const flushPara = () => {
    if (paraLines.length) {
      blocks.push({ type: "paragraph", text: paraLines.join(" ").trim() });
      paraLines = [];
    }
  };
  const flushList = () => {
    if (listItems.length) {
      blocks.push({ type: listType, items: [...listItems] });
      listItems = [];
      listType = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushPara();
      flushList();
      continue;
    }

    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      flushPara();
      flushList();
      blocks.push({ type: "heading", level: h[1].length, text: h[2].trim() });
      continue;
    }

    const ul = line.match(/^[-*]\s+(.*)$/);
    if (ul) {
      flushPara();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(ul[1].trim());
      continue;
    }

    const ol = line.match(/^\d+[.)]\s+(.*)$/);
    if (ol) {
      flushPara();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(ol[1].trim());
      continue;
    }

    if (/^[A-Za-z][A-Za-z\s/&,:-]{2,60}:$/.test(line)) {
      flushPara();
      flushList();
      blocks.push({ type: "heading", level: 3, text: line.slice(0, -1).trim() });
      continue;
    }

    flushList();
    paraLines.push(line);
  }
  flushPara();
  flushList();
  return blocks;
}

function buildStructuredHtml(markdown) {
  const blocks = parseMarkdownBlocks(markdown);
  const sections = [];
  let cur = null;

  for (const b of blocks) {
    if (b.type === "heading") {
      cur = { title: b.text, body: [] };
      sections.push(cur);
      continue;
    }
    if (!cur) {
      cur = { title: "Summary", body: [] };
      sections.push(cur);
    }
    cur.body.push(b);
  }

  if (!sections.length) {
    return '<div class="scan-review"><section class="scan-section"><div class="scan-section-body"><p>No analysis was returned.</p></div></section></div>';
  }

  function renderBlock(b) {
    if (b.type === "paragraph") return `<p>${renderInlineMarkdown(b.text)}</p>`;
    if (b.type === "ul" || b.type === "ol") {
      const tag = b.type;
      return `<${tag} class="scan-list">${b.items.map((i) => `<li>${renderInlineMarkdown(i)}</li>`).join("")}</${tag}>`;
    }
    return "";
  }

  const hero = sections[0];
  const rest = sections.slice(1);

  const heroHtml = `
    <section class="scan-hero">
      <div class="scan-section-kicker">Overview</div>
      <h3>${renderInlineMarkdown(hero.title)}</h3>
      <div class="scan-section-body">${hero.body.map(renderBlock).join("") || "<p>See sections below.</p>"}</div>
    </section>
  `;

  const sectionsHtml = rest
    .map((s) => {
      const accent = sectionAccentClass(s.title);
      return `
      <section class="scan-section ${accent}">
        <div class="scan-section-kicker">${sectionKicker(accent)}</div>
        <h3>${renderInlineMarkdown(s.title)}</h3>
        <div class="scan-section-body">${s.body.map(renderBlock).join("") || "<p>No items found.</p>"}</div>
      </section>
    `;
    })
    .join("");

  return `<div class="scan-review">${heroHtml}${sectionsHtml}</div>`;
}

const draftForm = document.getElementById("draft-form");
const draftFormPanel = document.getElementById("draft-form-panel");
const draftType = document.getElementById("draft-type");
const draftPartyA = document.getElementById("draft-party-a");
const draftPartyB = document.getElementById("draft-party-b");
const draftTerms = document.getElementById("draft-terms");
const draftJurisdiction = document.getElementById("draft-jurisdiction");
const draftBtn = document.getElementById("draft-btn");
const draftEmpty = document.getElementById("draft-empty");
const draftResultArea = document.getElementById("draft-result-area");
const draftProcessing = document.getElementById("draft-processing");
const draftOutput = document.getElementById("draft-output");
const draftResultTitle = document.getElementById("draft-result-title");
const copyDraftBtn = document.getElementById("copy-draft-btn");
const newDraftBtn = document.getElementById("new-draft-btn");

document.querySelectorAll(".type-chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    draftType.value = chip.dataset.type || draftType.value;
    document.querySelectorAll(".type-chip").forEach((c) => {
      c.classList.toggle("active", c === chip);
    });
  });
});

draftForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const type = draftType.value.trim();
  const partyA = draftPartyA.value.trim();
  const partyB = draftPartyB.value.trim();
  const terms = draftTerms.value.trim();
  const jur = draftJurisdiction.value.trim() || "India";

  if (!partyA || !partyB) {
    alert("Please enter both Party A and Party B.");
    return;
  }

  draftEmpty.classList.add("hidden");
  draftResultArea.classList.add("hidden");
  draftProcessing.classList.remove("hidden");
  draftBtn.disabled = true;

  try {
    const data = await fetchJson("/api/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_type: type,
        party_a: partyA,
        party_b: partyB,
        key_terms: terms || "Standard terms apply.",
        jurisdiction: jur,
      }),
    });

    draftResultTitle.textContent = data.documentType || type;
    draftOutput.textContent = data.document || "";
    draftResultArea.classList.remove("hidden");
    draftResultArea.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    draftEmpty.classList.remove("hidden");
    alert(`Draft error: ${err.message}`);
  } finally {
    draftProcessing.classList.add("hidden");
    draftBtn.disabled = false;
  }
});

copyDraftBtn.addEventListener("click", () => {
  const text = draftOutput.textContent;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    copyDraftBtn.textContent = "Copied";
    setTimeout(() => {
      copyDraftBtn.textContent = "Copy";
    }, 2000);
  });
});

newDraftBtn.addEventListener("click", () => {
  draftResultArea.classList.add("hidden");
  draftEmpty.classList.remove("hidden");
  draftForm.reset();
  draftJurisdiction.value = "India";
  document.querySelectorAll(".type-chip").forEach((c) => c.classList.remove("active"));
  draftFormPanel.scrollIntoView({ behavior: "smooth" });
});

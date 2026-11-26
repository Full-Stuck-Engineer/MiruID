import {
  makeBadge,
  renderExtractedFields,
  renderQualityPills,
  renderValidationChecks,
} from "./render.js";

const ALLOWED_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

const state = {
  file: null,
  previewUrl: null,
  documents: [],
  lastResponse: null,
};

const els = {
  root: document.getElementById("app-root"),
  form: document.getElementById("extract-form"),
  dropZone: document.getElementById("drop-zone"),
  fileInput: document.getElementById("file-input"),
  dropPlaceholder: document.getElementById("drop-placeholder"),
  previewWrap: document.getElementById("preview-wrap"),
  previewImg: document.getElementById("preview-img"),
  fileName: document.getElementById("file-name"),
  clearFileBtn: document.getElementById("clear-file-btn"),
  countrySelect: document.getElementById("country-select"),
  docTypeSelect: document.getElementById("doc-type-select"),
  submitBtn: document.getElementById("submit-btn"),
  submitSpinner: document.getElementById("submit-spinner"),
  submitLabel: document.getElementById("submit-label"),
  copyCurlBtn: document.getElementById("copy-curl-btn"),
  copyJsonBtn: document.getElementById("copy-json-btn"),
  resultsActions: document.getElementById("results-actions"),
  stateIdle: document.getElementById("state-idle"),
  stateLoading: document.getElementById("state-loading"),
  stateError: document.getElementById("state-error"),
  stateSuccess: document.getElementById("state-success"),
  errorCode: document.getElementById("error-code"),
  errorRequestId: document.getElementById("error-request-id"),
  errorMessage: document.getElementById("error-message"),
  docBadges: document.getElementById("doc-badges"),
  metaBadges: document.getElementById("meta-badges"),
  qualityPills: document.getElementById("quality-pills"),
  validationSummary: document.getElementById("validation-summary"),
  validationList: document.getElementById("validation-list"),
  fieldsTbody: document.getElementById("fields-tbody"),
  rawJsonPre: document.getElementById("raw-json-pre"),
};

function setUiState(nextState) {
  els.root.dataset.state = nextState;
  const isLoading = nextState === "loading";

  els.stateIdle.hidden = nextState !== "idle";
  els.stateLoading.hidden = !isLoading;
  els.stateError.hidden = nextState !== "error";
  els.stateSuccess.hidden = nextState !== "success";
  els.resultsActions.hidden = nextState !== "success";

  els.submitSpinner.hidden = !isLoading;
  els.submitLabel.textContent = isLoading ? "Extracting..." : "Extract Document";
  els.submitBtn.disabled = isLoading || !state.file;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function showError({ error_code, message, request_id }) {
  els.errorCode.textContent = error_code || "REQUEST_FAILED";
  els.errorMessage.textContent = message || "An unexpected error occurred.";
  els.errorRequestId.textContent = request_id ? `request_id: ${request_id}` : "";
  setUiState("error");
}

function clearSelectedFile() {
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.file = null;
  state.previewUrl = null;
  els.fileInput.value = "";
  els.previewImg.removeAttribute("src");
  els.previewWrap.hidden = true;
  els.dropPlaceholder.hidden = false;
  els.submitBtn.disabled = true;
}

function setSelectedFile(file) {
  if (!file) {
    clearSelectedFile();
    return;
  }
  if (!ALLOWED_MIME_TYPES.has(file.type)) {
    showError({
      error_code: "UNSUPPORTED_MEDIA_TYPE",
      message: "Please select a JPEG, PNG, or WebP image.",
      request_id: null,
    });
    return;
  }

  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.file = file;
  state.previewUrl = URL.createObjectURL(file);
  els.previewImg.src = state.previewUrl;
  els.fileName.textContent = `${file.name} (${formatBytes(file.size)})`;
  els.dropPlaceholder.hidden = true;
  els.previewWrap.hidden = false;
  els.submitBtn.disabled = false;
  if (els.root.dataset.state === "error") setUiState("idle");
}

function populateCountryDropdown() {
  const countries = [...new Set(state.documents.map((d) => d.country_code))].sort();
  els.countrySelect.innerHTML = "";
  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "Auto-Detect";
  els.countrySelect.appendChild(autoOpt);

  for (const code of countries) {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = code;
    els.countrySelect.appendChild(opt);
  }
}

function populateDocTypeDropdown() {
  const selectedCountry = els.countrySelect.value;
  const previousDocType = els.docTypeSelect.value;
  const filtered = selectedCountry
    ? state.documents.filter((d) => d.country_code === selectedCountry)
    : state.documents;
  const docTypes = [...new Set(filtered.map((d) => d.doc_type))].sort();

  els.docTypeSelect.innerHTML = "";
  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "Auto-Detect";
  els.docTypeSelect.appendChild(autoOpt);

  for (const docType of docTypes) {
    const match = filtered.find((d) => d.doc_type === docType);
    const opt = document.createElement("option");
    opt.value = docType;
    opt.textContent = match?.description ? `${docType} — ${match.description}` : docType;
    els.docTypeSelect.appendChild(opt);
  }

  if (docTypes.includes(previousDocType)) {
    els.docTypeSelect.value = previousDocType;
  }
}

async function loadSupportedDocuments() {
  try {
    const res = await fetch("/v1/documents");
    if (!res.ok) return;
    const payload = await res.json();
    state.documents = Array.isArray(payload.documents) ? payload.documents : [];
    populateCountryDropdown();
    populateDocTypeDropdown();
  } catch {
    // Keep Auto-Detect defaults if discovery fails.
  }
}

function renderSuccess(payload) {
  state.lastResponse = payload;

  els.docBadges.innerHTML = "";
  const doc = payload.document || {};
  els.docBadges.appendChild(
    makeBadge(`${doc.country_code || "?"} / ${doc.doc_type || "?"}`, "info"),
  );
  els.docBadges.appendChild(
    doc.detected_automatically
      ? makeBadge("Auto-Detected", "success")
      : makeBadge("Manual Selection"),
  );

  els.metaBadges.innerHTML = "";
  const meta = payload.meta || {};
  const latency =
    typeof meta.processing_ms === "number" ? `${meta.processing_ms.toFixed(1)} ms` : "n/a";
  els.metaBadges.appendChild(makeBadge(latency));
  if (meta.strategy) els.metaBadges.appendChild(makeBadge(meta.strategy));

  renderQualityPills(els.qualityPills, meta.quality || null);
  renderValidationChecks(els.validationSummary, els.validationList, payload.validation);
  renderExtractedFields(els.fieldsTbody, payload.data);
  els.rawJsonPre.textContent = JSON.stringify(payload, null, 2);

  setUiState("success");
}

function buildCurlCommand() {
  const endpoint = `${window.location.origin}/v1/extract`;
  const filename = state.file ? state.file.name : "document.jpg";
  const parts = [`curl -X POST "${endpoint}"`, `-F "file=@${filename}"`];
  if (els.countrySelect.value) parts.push(`-F "country=${els.countrySelect.value}"`);
  if (els.docTypeSelect.value) parts.push(`-F "doc_type=${els.docTypeSelect.value}"`);
  return parts.join(" \\\n  ");
}

async function copyTextWithFeedback(button, text) {
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied!";
  } catch {
    button.textContent = "Copy failed";
  }
  setTimeout(() => {
    button.textContent = original;
  }, 1500);
}

async function handleSubmit(event) {
  event.preventDefault();
  if (!state.file) return;

  setUiState("loading");
  const formData = new FormData();
  formData.append("file", state.file);
  if (els.countrySelect.value) formData.append("country", els.countrySelect.value);
  if (els.docTypeSelect.value) formData.append("doc_type", els.docTypeSelect.value);

  try {
    const response = await fetch("/v1/extract", { method: "POST", body: formData });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;

    if (!response.ok) {
      showError({
        error_code: payload?.error_code || `HTTP_${response.status}`,
        message: payload?.message || payload?.detail || response.statusText || "Extraction failed.",
        request_id: payload?.request_id || response.headers.get("x-request-id"),
      });
      return;
    }

    renderSuccess(payload);
  } catch (err) {
    showError({
      error_code: "NETWORK_ERROR",
      message: err instanceof Error ? err.message : "Unable to reach MiruID API.",
      request_id: null,
    });
  }
}

els.dropZone.addEventListener("click", (event) => {
  if (event.target === els.clearFileBtn) return;
  els.fileInput.click();
});
els.dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.fileInput.click();
  }
});
els.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  els.dropZone.classList.add("drag-over");
});
els.dropZone.addEventListener("dragleave", () => els.dropZone.classList.remove("drag-over"));
els.dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  els.dropZone.classList.remove("drag-over");
  const dropped = event.dataTransfer?.files?.[0];
  if (dropped) setSelectedFile(dropped);
});

els.fileInput.addEventListener("change", () => {
  const picked = els.fileInput.files?.[0];
  if (picked) setSelectedFile(picked);
});
els.clearFileBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  clearSelectedFile();
});
els.countrySelect.addEventListener("change", populateDocTypeDropdown);
els.form.addEventListener("submit", handleSubmit);
els.copyCurlBtn.addEventListener("click", () =>
  copyTextWithFeedback(els.copyCurlBtn, buildCurlCommand()),
);
els.copyJsonBtn.addEventListener("click", () => {
  if (!state.lastResponse) return;
  copyTextWithFeedback(els.copyJsonBtn, JSON.stringify(state.lastResponse, null, 2));
});

loadSupportedDocuments();
setUiState("idle");

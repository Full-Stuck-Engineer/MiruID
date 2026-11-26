export function makeBadge(text, variant = "") {
  const span = document.createElement("span");
  span.className = variant ? `badge badge-${variant}` : "badge";
  span.textContent = text;
  return span;
}

export function renderQualityPills(container, quality) {
  container.innerHTML = "";
  if (!quality) {
    container.appendChild(makeBadge("Quality metrics unavailable"));
    return;
  }

  const blurScore =
    typeof quality.blur_score === "number" ? quality.blur_score.toFixed(1) : "n/a";
  container.appendChild(makeBadge(`blur_score: ${blurScore}`, "info"));
  container.appendChild(
    makeBadge(
      quality.is_blurry ? "is_blurry: true" : "is_blurry: false",
      quality.is_blurry ? "danger" : "success",
    ),
  );
  container.appendChild(
    makeBadge(
      quality.has_glare ? "has_glare: true" : "has_glare: false",
      quality.has_glare ? "warn" : "success",
    ),
  );
}

export function renderValidationChecks(summaryEl, listEl, validation) {
  listEl.innerHTML = "";
  const isValid = Boolean(validation?.is_valid);
  summaryEl.className = `badge ${isValid ? "badge-success" : "badge-danger"}`;
  summaryEl.textContent = isValid ? "VALID" : "INVALID";

  const checks = Array.isArray(validation?.checks) ? validation.checks : [];
  if (checks.length === 0) {
    const li = document.createElement("li");
    li.className = "check-item";
    li.textContent = "No deterministic validation checks reported.";
    listEl.appendChild(li);
    return;
  }

  for (const check of checks) {
    const li = document.createElement("li");
    li.className = "check-item";
    li.appendChild(makeBadge(check.passed ? "PASS" : "FAIL", check.passed ? "success" : "danger"));

    const nameSpan = document.createElement("strong");
    nameSpan.textContent = check.name;
    li.appendChild(nameSpan);

    if (check.message) {
      const msgSpan = document.createElement("span");
      msgSpan.className = "check-msg";
      msgSpan.textContent = `— ${check.message}`;
      li.appendChild(msgSpan);
    }
    listEl.appendChild(li);
  }
}

function formatConfidenceBadge(confidence) {
  if (typeof confidence !== "number") {
    return makeBadge("—");
  }
  const pct = `${Math.round(confidence * 100)}%`;
  if (confidence >= 0.85) return makeBadge(pct, "success");
  if (confidence >= 0.6) return makeBadge(pct, "warn");
  return makeBadge(pct, "danger");
}

export function renderExtractedFields(tbody, data) {
  tbody.innerHTML = "";
  const entries = data && typeof data === "object" ? Object.entries(data) : [];

  if (entries.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 3;
    td.textContent = "No fields extracted.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const [key, rawVal] of entries) {
    const tr = document.createElement("tr");
    const isFieldObj =
      rawVal !== null &&
      typeof rawVal === "object" &&
      !Array.isArray(rawVal) &&
      "value" in rawVal;
    const displayValue = isFieldObj ? rawVal.value : rawVal;
    const confidence = isFieldObj ? rawVal.confidence : null;

    const fieldTd = document.createElement("td");
    fieldTd.textContent = key;

    const valueTd = document.createElement("td");
    if (displayValue === null || displayValue === undefined || displayValue === "") {
      const nullTag = document.createElement("span");
      nullTag.className = "null-indicator";
      nullTag.textContent = "null";
      valueTd.appendChild(nullTag);
    } else if (typeof displayValue === "object") {
      valueTd.textContent = JSON.stringify(displayValue);
    } else {
      valueTd.textContent = String(displayValue);
    }

    const confTd = document.createElement("td");
    confTd.appendChild(formatConfidenceBadge(confidence));

    tr.append(fieldTd, valueTd, confTd);
    tbody.appendChild(tr);
  }
}

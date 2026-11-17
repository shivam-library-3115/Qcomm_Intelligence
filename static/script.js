const form = document.getElementById("check-form");
const skuEl = document.getElementById("sku");
const platformEl = document.getElementById("platform");
const pincodesEl = document.getElementById("pincodes");
const runBtn = document.getElementById("run-btn");
const csvBtn = document.getElementById("csv-btn");
const progress = document.getElementById("progress");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const summary = document.getElementById("summary");
const resultsWrap = document.getElementById("results-wrap");
const resultsBody = document.getElementById("results-body");
const errorBox = document.getElementById("error-box");

const CSV_COLS = ["Platform", "Product ID", "Product Name", "Brand", "Pack Size",
  "Pincode", "City", "Pincode Status", "Availability", "Selling Price", "MRP",
  "Discount", "Inventory", "Store ID", "Note"];

let lastRows = [];
let lastMeta = { sku: "", platform: "" };

function badgeClass(v) {
  if (v === "In Stock") return "ok";
  if (v === "Out of Stock") return "oos";
  if (v === "Error") return "err";
  return "na";
}

function cell(v) { return (v === null || v === undefined || v === "") ? "—" : String(v); }

function addRow(r) {
  const tr = document.createElement("tr");
  const price = r["Selling Price"];
  const mrp = r["MRP"];
  tr.innerHTML = `
    <td>${cell(r["Pincode"])}</td>
    <td>${cell(r["City"])}</td>
    <td><span class="badge ${badgeClass(r["Availability"])}">${cell(r["Availability"])}</span></td>
    <td>${cell(r["Product Name"])}</td>
    <td>${cell(r["Pack Size"])}</td>
    <td class="num">${price != null && price !== "" ? "₹" + price : "—"}</td>
    <td class="num">${mrp != null && mrp !== "" ? "₹" + mrp : "—"}</td>
    <td class="num">${cell(r["Discount"])}</td>
    <td class="num">${cell(r["Inventory"])}</td>
    <td class="note">${cell(r["Note"])}</td>`;
  resultsBody.appendChild(tr);
}

function renderSummary(counts) {
  const defs = [
    ["In Stock", "ok", "In stock"],
    ["Out of Stock", "oos", "Out of stock"],
    ["Not available here", "na", "Not available"],
    ["Error", "err", "Errors"],
  ];
  summary.innerHTML = defs
    .filter(([k]) => counts[k])
    .map(([k, cls, label]) => `<span class="chip ${cls}"><span class="n">${counts[k]}</span> ${label}</span>`)
    .join("");
  summary.hidden = false;
}

function toCSV(rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [CSV_COLS.join(",")];
  rows.forEach((r) => lines.push(CSV_COLS.map((c) => esc(r[c])).join(",")));
  return lines.join("\r\n");
}

csvBtn.addEventListener("click", () => {
  const blob = new Blob([toCSV(lastRows)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
  a.href = url;
  a.download = `availability_${lastMeta.platform || "result"}_${lastMeta.sku || "sku"}_${stamp}.csv`.replace(/\s+/g, "_");
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const sku = skuEl.value.trim();
  const platform = platformEl.value;
  const pincodes = pincodesEl.value.trim();
  if (!sku || !pincodes) return;

  runBtn.disabled = true;
  runBtn.textContent = "Checking…";
  csvBtn.hidden = true;
  errorBox.hidden = true;
  resultsBody.innerHTML = "";
  resultsWrap.hidden = true;
  summary.hidden = true;
  progress.hidden = false;
  progressFill.style.width = "0%";
  progressText.textContent = "Starting…";
  lastRows = [];

  try {
    const resp = await fetch("/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku, platform, pincodes }),
    });
    if (!resp.ok || !resp.body) {
      if (resp.status === 401) { window.location.href = "/login"; return; }
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `Request failed (${resp.status})`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let total = 0;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop();
      for (const raw of chunks) {
        if (!raw.trim() || raw.startsWith(":")) continue;
        let ev = "message", dataStr = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) dataStr += line.slice(5).replace(/^ /, "");
        }
        let data = {};
        try { data = JSON.parse(dataStr); } catch (_) { continue; }

        if (ev === "start") {
          total = data.total;
          resultsWrap.hidden = false;
          progressText.textContent = `0 / ${total}`;
          if (data.truncated) {
            errorBox.hidden = false;
            errorBox.textContent = `Note: limited to the first ${data.max} pincodes per run.`;
          }
        } else if (ev === "status") {
          progressText.textContent = `${data.i} / ${total} · ${data.pincode} — ${data.msg}`;
        } else if (ev === "row") {
          const rows = data.rows || [data.row];
          rows.forEach(addRow);
          progressFill.style.width = `${Math.round((data.i / total) * 100)}%`;
          progressText.textContent = `${data.i} / ${total}`;
        } else if (ev === "done") {
          renderSummary(data.counts);
          lastRows = data.rows || [];
          lastMeta = { sku: data.sku, platform: data.platform };
          progressFill.style.width = "100%";
          progressText.textContent = `Done — ${total} pincode(s)`;
          if (lastRows.length) csvBtn.hidden = false;
        } else if (ev === "error") {
          throw new Error(data.error || "Something went wrong.");
        }
      }
    }
  } catch (err) {
    errorBox.hidden = false;
    errorBox.textContent = err.message || "Something went wrong.";
  } finally {
    runBtn.disabled = false;
    runBtn.textContent = "Check availability";
  }
});

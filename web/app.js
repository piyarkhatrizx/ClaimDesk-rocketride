// =============================================================================
// ClaimDesk — Frontend Application
// Handles file uploads, pipeline communication, claim rendering, and chat.
// =============================================================================

// ---- ELEMENTS ----
const fileInput = document.getElementById('file-input');
const dropzone = document.getElementById('dropzone');
const thumbs = document.getElementById('thumbs');
const submitBtn = document.getElementById('submit');
const steps = document.getElementById('steps');
const statusEl = document.getElementById('status');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const resultBody = document.getElementById('result-body');
const connDot = document.getElementById('conn-dot');
const connText = document.getElementById('conn-text');
const chatPanel = document.getElementById('chat-panel');
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');
const historyToggle = document.getElementById('toggle-history');
const sidebar = document.querySelector('.sidebar');

let files = [];
let currentClaimContext = null;
let chatHistory = [];

// =============================================================================
// FILE HANDLING
// Drag-and-drop + click-to-browse for damage photos
// =============================================================================
dropzone.addEventListener('click', () => fileInput.click());
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
dropzone.addEventListener('drop', e => {
  e.preventDefault(); dropzone.classList.remove('drag');
  addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => addFiles(fileInput.files));

function addFiles(list) {
  for (const f of list) {
    if (!f.type.startsWith('image/')) continue;
    files.push(f);
  }
  renderThumbs();
}

function renderThumbs() {
  thumbs.innerHTML = '';
  files.forEach((f, i) => {
    const div = document.createElement('div');
    div.className = 'thumb';
    const url = URL.createObjectURL(f);
    div.innerHTML = `<img src="${url}" alt=""><button data-i="${i}">×</button>`;
    thumbs.appendChild(div);
  });
  thumbs.querySelectorAll('button').forEach(b => {
    b.onclick = () => { files.splice(+b.dataset.i, 1); renderThumbs(); };
  });
}

// =============================================================================
// UI HELPERS
// =============================================================================
function setStep(name, state) {
  const el = steps.querySelector(`[data-step="${name}"]`);
  if (!el) return;
  el.classList.remove('active', 'done');
  if (state) el.classList.add(state);
}

function setStatus(text, cls) {
  statusText.textContent = text;
  statusDot.className = 'dot' + (cls ? ' ' + cls : '');
}

// =============================================================================
// PIPELINE CONNECTION CHECK
// Polls /pipeline-status every 5 seconds
// =============================================================================
async function checkConnection() {
  try {
    const res = await fetch('/pipeline-status');
    const data = await res.json();
    if (data.port) {
      connDot.className = 'dot ok';
      connText.textContent = `Connected to pipeline (port ${data.port})`;
      return true;
    }
  } catch (_) {}
  connDot.className = 'dot err';
  connText.textContent = 'Pipeline not found — press ▶ on the Webhook node in RocketRide.';
  return false;
}
checkConnection();
setInterval(checkConnection, 5000);

// =============================================================================
// CLAIM HISTORY
// Stores processed claims in localStorage for later review
// =============================================================================
function getHistory() {
  try { return JSON.parse(localStorage.getItem('claimdesk_history') || '[]'); }
  catch { return []; }
}

function saveHistory(history) {
  localStorage.setItem('claimdesk_history', JSON.stringify(history));
}

function addToHistory(claimData) {
  const history = getHistory();
  history.unshift(claimData);
  if (history.length > 50) history.pop();
  saveHistory(history);
  renderHistory();
}

function renderHistory() {
  const list = document.getElementById('sidebar-list');
  const empty = document.getElementById('sidebar-empty');
  const history = getHistory();

  list.querySelectorAll('.sidebar-item').forEach(n => n.remove());

  if (history.length === 0) {
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  history.forEach(item => {
    const div = document.createElement('div');
    div.className = 'sidebar-item';
    const badgeColor =
      item.triage === 'HIGH PRIORITY' ? '#ff5c5c' :
      item.triage === 'FAST TRACK' ? '#2ecc71' : '#4f8cff';

    div.innerHTML = `
      <div class="si-id">${item.claimId}</div>
      <div class="si-date">${item.date}</div>
      <div class="si-summary">${item.summary || 'No summary'}</div>
      <span class="si-badge" style="background:${badgeColor}">${item.triage || 'PENDING'}</span>
    `;
    div.addEventListener('click', (event) => loadHistoryItem(event, item));
    list.appendChild(div);
  });
}

function loadHistoryItem(event, item) {
  document.querySelectorAll('.sidebar-item').forEach(s => s.classList.remove('active'));
  event.currentTarget.classList.add('active');
  resultBody.innerHTML = item.resultHtml || '<div class="placeholder">No data stored.</div>';
  reattachTabs();
}

document.getElementById('clear-history').addEventListener('click', () => {
  if (confirm('Clear all claim history?')) {
    localStorage.removeItem('claimdesk_history');
    renderHistory();
    resultBody.innerHTML = '<div class="placeholder">No claim submitted yet.</div>';
  }
});
renderHistory();

// =============================================================================
// CLAIM ID GENERATOR
// Format: CLM-YYMM-XXXX
// =============================================================================
function generateClaimId() {
  const now = new Date();
  const yr = now.getFullYear().toString().slice(-2);
  const mn = String(now.getMonth() + 1).padStart(2, '0');
  const seq = String(Math.floor(Math.random() * 9000) + 1000);
  return `CLM-${yr}${mn}-${seq}`;
}

// =============================================================================
// CONFIDENCE SCORE BARS
// Renders per-field confidence (0-100%) with color coding
// =============================================================================
function buildConfidenceBars(confidence) {
  if (!confidence || typeof confidence !== 'object') return '';
  const fields = ['summary', 'severity', 'damaged_parts', 'estimated_cost_range', 'drivable'];
  let html = '<div class="confidence-section"><strong style="font-size:12px;color:var(--muted);display:block;margin-bottom:10px;">AI Confidence Scores</strong>';
  fields.forEach(f => {
    const val = confidence[f];
    if (val === undefined) return;
    const pct = Math.round(val);
    const color = pct >= 80 ? '#2ecc71' : pct >= 60 ? '#f5a623' : '#ff5c5c';
    const label = f.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    html += `
      <div class="confidence-row">
        <span class="confidence-label">${label}</span>
        <div class="confidence-bar-bg"><div class="confidence-bar" style="width:${pct}%;background:${color};"></div></div>
        <span class="confidence-val" style="color:${color}">${pct}%</span>
      </div>`;
  });
  html += '</div>';
  return html;
}

// =============================================================================
// CROSS-CHECK DISPLAY
// Shows match/mismatch between description and vision analysis
// =============================================================================
function buildCrosscheckHtml(crosscheck) {
  if (!crosscheck) return '';
  const cls = crosscheck.match ? 'match' : 'mismatch';
  const icon = crosscheck.match ? '✅' : '⚠️';
  const title = crosscheck.match ? 'Description & photo analysis are consistent' : 'Contradictions detected between description and photo';
  let html = `<div class="crosscheck-box ${cls}"><strong>${icon} ${title}</strong>`;
  if (crosscheck.details) {
    html += `<p style="margin:8px 0 0; font-size:12px;">${crosscheck.details}</p>`;
  }
  if (crosscheck.contradictions && crosscheck.contradictions.length > 0) {
    html += '<ul style="margin:8px 0 0; padding-left:18px; font-size:12px;">';
    crosscheck.contradictions.forEach(c => { html += `<li>${c}</li>`; });
    html += '</ul>';
  }
  html += '</div>';
  return html;
}

// =============================================================================
// COVERAGE ASSESSMENT DISPLAY
// Shows eligibility, payout estimate, and recommendation
// =============================================================================
function buildCoverageHtml(coverage) {
  if (!coverage) return '';
  const eligible = coverage.eligible;
  const cls = eligible ? 'match' : 'mismatch';
  const icon = eligible ? '✅' : '❌';
  const title = eligible ? 'Eligible: ' + coverage.type : 'Not Eligible for Payout';
  let html = '<div class="crosscheck-box ' + cls + '"><strong>' + icon + ' ' + title + '</strong>';
  html += '<p style="margin:8px 0 0;font-size:12px;">' + (coverage.recommendation || '') + '</p>';
  if (eligible && coverage.estimated_payout) {
    html += '<div style="display:flex;gap:16px;margin-top:8px;font-size:12px;">';
    html += '<span>Deductible: <strong>$' + (coverage.deductible || 0).toLocaleString() + '</strong></span>';
    html += '<span>Est. Payout: <strong>$' + (coverage.estimated_payout || 0).toLocaleString() + '</strong></span>';
    html += '</div>';
  }
  html += '</div>';
  return html;
}

// =============================================================================
// CLAIM REPORT CARD BUILDER
// Assembles the full claim report HTML from pipeline response data
// =============================================================================
function buildCardHtml(resData, rawText) {
  try {
    // Privacy badge
    let privacyHtml = '';
    const removed = resData?._privacy?.removed || {};
    const items = [];
    if (removed.gps) items.push(`📍 GPS location: ${removed.gps}`);
    if (removed.timestamp) items.push(`🕐 Timestamp: ${removed.timestamp}`);
    if (removed.device) items.push(`📱 Device: ${removed.device}`);

    if (items.length) {
      privacyHtml = `
        <div style="background:#12261a;border:1px solid #1f5133;border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:13px;color:#8fdcae;">
          <strong style="color:#b6f2cd;">🔒 Privacy: stripped before processing</strong><br>
          ${items.join('<br>')}
        </div>`;
    } else if (resData?._privacy) {
      privacyHtml = `
        <div style="background:var(--panel-2);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:13px;color:var(--muted);">
          🔒 Image metadata scrubbed (no GPS/device data was present).
        </div>`;
    }

    // Cross-check and coverage
    const crosscheckHtml = buildCrosscheckHtml(resData?._crosscheck);
    const coverageHtml = buildCoverageHtml(resData?.claim?.coverage);

    if (resData.success && resData.claim) {
      const claim = resData.claim;
      const audit = resData._audit;

      let badgeColor = "#4f8cff";
      if (audit.triage_level === "HIGH PRIORITY") badgeColor = "#ff5c5c";
      if (audit.triage_level === "FAST TRACK") badgeColor = "#2ecc71";

      // Audit flags
      let flagsHtml = "";
      if (audit.flags && audit.flags.length > 0) {
        flagsHtml = `
          <div style="background:#2a1818; border:1px solid #ff5c5c; border-radius:8px; padding:10px 12px; margin-bottom:12px; font-size:12px; color:#ff8e8e;">
            <strong>⚠️ Audit Discrepancies Flagged:</strong>
            <ul style="margin:4px 0 0; padding-left:18px;">
              ${audit.flags.map(f => `<li>${f}</li>`).join('')}
            </ul>
          </div>`;
      }

      // Damaged parts badges
      const partsBadges = (claim.damaged_parts || [])
        .map(p => `<span style="background:var(--panel); border:1px solid var(--border); padding:2px 8px; border-radius:6px; font-size:12px;">${p}</span>`)
        .join(' ');

      // Confidence bars
      const confidenceHtml = buildConfidenceBars(claim.confidence || resData._confidence);

      return privacyHtml + crosscheckHtml + coverageHtml + flagsHtml + `
        <div style="background:var(--panel-2); border:1px solid var(--border); border-radius:12px; padding:16px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <span style="font-weight:600; font-size:14px;">Claim Summary</span>
            <span style="background:${badgeColor}; color:#fff; font-size:11px; font-weight:700; padding:3px 10px; border-radius:20px;">
              ${audit.triage_level}
            </span>
          </div>
          <p style="font-size:13px; margin:0 0 14px; color:var(--text);">${claim.summary}</p>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:12px; background:var(--panel); padding:12px; border-radius:8px; margin-bottom:12px;">
            <div><strong style="color:var(--muted);">Severity:</strong> ${claim.severity}</div>
            <div><strong style="color:var(--muted);">Est. Cost:</strong> ${claim.estimated_cost_range}</div>
            <div><strong style="color:var(--muted);">Drivable:</strong> ${claim.drivable ? '✅ Yes' : '❌ No'}</div>
            <div><strong style="color:var(--muted);">Audited At:</strong> ${audit.processed_at.split(' ')[1]}</div>
          </div>
          <div style="font-size:12px; margin-bottom:14px;">
            <strong style="color:var(--muted); display:block; margin-bottom:6px;">Damaged Components:</strong>
            <div style="display:flex; flex-wrap:wrap; gap:6px;">${partsBadges || 'None identified'}</div>
          </div>
          ${confidenceHtml}
        </div>
      `;
    } else {
      return privacyHtml + crosscheckHtml + coverageHtml + `<pre class="report">${resData.raw_text || rawText}</pre>`;
    }
  } catch (e) {
    return `<pre class="report">${rawText}</pre>`;
  }
}

// =============================================================================
// TAB RE-ATTACHMENT
// Re-binds tab click handlers after dynamic content is inserted
// =============================================================================
function reattachTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.target).classList.add('active');
    });
  });
}

// =============================================================================
// CLAIM SUBMISSION
// Sends photos + description to serve.py, displays results
// =============================================================================
submitBtn.addEventListener('click', async () => {
  const description = document.getElementById('description').value.trim();
  const policy = document.getElementById('policy').value.trim();

  if (files.length === 0 && !description) { alert('Add at least one photo or a description.'); return; }

  const claimId = generateClaimId();

  submitBtn.disabled = true;
  steps.style.display = 'flex';
  statusEl.style.display = 'flex';
  resultBody.innerHTML = '<div class="placeholder">Processing claim... (vision analysis takes time)</div>';

  ['upload','processing','crosscheck','report'].forEach(s => setStep(s, ''));
  setStep('upload', 'active');

  let allResults = [];

  try {
    const meta = [
      description ? `Accident description: ${description}` : '',
      policy ? `Policy number: ${policy}` : ''
    ].filter(Boolean).join('\n');

    if (files.length > 0) {
      for (let i = 0; i < files.length; i++) {
        setStep('upload', 'done');
        setStep('processing', 'active');
        setStatus(`Processing photo ${i + 1} of ${files.length}…`, 'run');

        const res = await fetch('/submit', {
          method: 'POST',
          headers: {
            'Content-Type': files[i].type || 'image/jpeg',
            'X-Claim-Description': encodeURIComponent(description || ''),
            'X-Claim-Id': claimId
          },
          body: files[i]
        });

        const raw = await res.text();
        if (!res.ok) throw new Error(raw || `Proxy returned ${res.status}`);

        try {
          allResults.push({ title: `Photo ${i + 1}`, data: JSON.parse(raw), raw: raw });
        } catch(e) {
          allResults.push({ title: `Photo ${i + 1}`, data: {}, raw: raw });
        }
      }
    } else {
      setStep('upload', 'done');
      setStep('processing', 'active');
      setStatus('Processing textual claim info…', 'run');
      const res = await fetch('/submit', {
        method: 'POST',
        headers: {
          'Content-Type': 'text/plain',
          'X-Claim-Id': claimId
        },
        body: meta
      });
      const raw = await res.text();
      if (!res.ok) throw new Error(raw || `Proxy returned ${res.status}`);
      try {
        allResults.push({ title: 'Report', data: JSON.parse(raw), raw: raw });
      } catch(e) {
        allResults.push({ title: 'Report', data: {}, raw: raw });
      }
    }

    // Steps done
    setStep('processing', 'done');
    setStep('crosscheck', 'done');
    setStep('report', 'done');
    setStatus('Claim batch processed', 'ok');

    // Build tabs
    let tabsHtml = `<div style="font-size:12px;color:var(--muted);margin-bottom:12px;">Claim ID: <strong style="color:var(--accent);">${claimId}</strong></div>`;
    tabsHtml += '<div class="tabs">';
    let contentHtml = '';

    allResults.forEach((res, i) => {
      const isActive = i === 0 ? 'active' : '';
      tabsHtml += `<button class="tab-btn ${isActive}" data-target="tab-${i}">${res.title}</button>`;
      contentHtml += `<div class="tab-content ${isActive}" id="tab-${i}">` + buildCardHtml(res.data, res.raw) + `</div>`;
    });
    tabsHtml += '</div>';

    const exportHtml = `
      <div class="export-bar">
        <button class="btn-sm" id="export-json">📥 Export Batch JSON</button>
        <button class="btn-sm" id="export-pdf">📄 Print / Save PDF</button>
      </div>`;

    resultBody.innerHTML = tabsHtml + contentHtml + exportHtml;
    reattachTabs();

    // Save to history
    const firstClaim = allResults[0]?.data?.claim || {};
    const firstAudit = allResults[0]?.data?._audit || {};
    addToHistory({
      claimId: claimId,
      date: new Date().toLocaleString(),
      summary: firstClaim.summary || 'Processing completed',
      triage: firstAudit.triage_level || 'STANDARD',
      policy: policy || 'N/A',
      resultHtml: resultBody.innerHTML
    });

    // Activate chat panel with claim context
    const firstResult = allResults[0]?.data || {};
    showChat(firstResult);

    // PDF export
    document.getElementById('export-pdf').addEventListener('click', () => {
      const pdfBtn = document.getElementById('export-pdf');
      pdfBtn.innerText = "⏳ Generating PDF...";
      pdfBtn.disabled = true;

      const printContainer = document.createElement('div');
      printContainer.style.padding = '20px';
      printContainer.style.background = '#fff';
      printContainer.style.color = '#000';
      printContainer.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

      const mainTitle = document.createElement('h2');
      mainTitle.innerText = `ClaimDesk Incident Report — ${claimId}`;
      mainTitle.style.borderBottom = '2px solid #000';
      mainTitle.style.paddingBottom = '10px';
      mainTitle.style.marginBottom = '20px';
      printContainer.appendChild(mainTitle);

      const allTabs = document.querySelectorAll('.tab-content');
      allTabs.forEach((tab, index) => {
        const tabTitle = document.querySelectorAll('.tab-btn')[index]?.innerText || `Section ${index+1}`;
        const section = document.createElement('div');
        section.style.marginBottom = '30px';
        section.style.pageBreakInside = 'avoid';
        const heading = document.createElement('h3');
        heading.innerText = tabTitle;
        section.appendChild(heading);
        const clone = tab.cloneNode(true);
        clone.style.display = 'block';
        clone.innerHTML = clone.innerHTML
          .replace(/var\(--panel-2\)/g, '#f9f9f9')
          .replace(/var\(--panel\)/g, '#fff')
          .replace(/var\(--border\)/g, '#ddd')
          .replace(/var\(--text\)/g, '#111')
          .replace(/var\(--muted\)/g, '#555');
        section.appendChild(clone);
        printContainer.appendChild(section);
      });

      const opt = {
        margin: 0.5,
        filename: `ClaimDesk_${claimId}_${Date.now()}.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'in', format: 'letter', orientation: 'portrait' }
      };

      html2pdf().set(opt).from(printContainer).save().then(() => {
        pdfBtn.innerText = "📄 Print / Save PDF";
        pdfBtn.disabled = false;
      });
    });

    // JSON export
    document.getElementById('export-json').addEventListener('click', () => {
      const exportPayload = {
        claim_id: claimId,
        exported_at: new Date().toISOString(),
        policy_number: policy || "N/A",
        items: allResults.map(r => r.data)
      };
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exportPayload, null, 2));
      const dl = document.createElement('a');
      dl.setAttribute("href", dataStr);
      dl.setAttribute("download", `ClaimDesk_${claimId}.json`);
      document.body.appendChild(dl);
      dl.click();
      dl.remove();
    });

  } catch (err) {
    setStatus('Error', 'err');
    resultBody.innerHTML = `<pre class="report">Could not process the claim.\n\n${err.message}</pre>`;
  } finally {
    submitBtn.disabled = false;
  }
});

// =============================================================================
// ADJUSTER CHAT
// Sends questions to Ollama with the claim report as context
// =============================================================================
function showChat(claimData) {
  currentClaimContext = claimData;
  chatPanel.classList.add('visible');
  chatMessages.innerHTML = '';
  chatHistory = [
    { role: 'user', content: 'You are assisting an insurance adjuster reviewing this claim:\n' + JSON.stringify(claimData, null, 2) },
    { role: 'assistant', content: 'I have the claim report loaded. Ask me anything about this claim.' }
  ];
}

async function sendChatMessage(text) {
  const userDiv = document.createElement('div');
  userDiv.className = 'chat-msg user';
  userDiv.textContent = text;
  chatMessages.appendChild(userDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  chatHistory.push({ role: 'user', content: text });

  chatSend.disabled = true;
  chatInput.disabled = true;
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: chatHistory })
    });
    const data = await res.json();
    const reply = data.reply || data.error || 'No response';

    chatHistory.push({ role: 'assistant', content: reply });

    const assistantDiv = document.createElement('div');
    assistantDiv.className = 'chat-msg assistant';
    assistantDiv.textContent = reply;
    chatMessages.appendChild(assistantDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  } catch (err) {
    const errDiv = document.createElement('div');
    errDiv.className = 'chat-msg assistant';
    errDiv.textContent = 'Error connecting to chat.';
    chatMessages.appendChild(errDiv);
  } finally {
    chatSend.disabled = false;
    chatInput.disabled = false;
    chatInput.focus();
  }
}

chatSend.addEventListener('click', () => {
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';
  sendChatMessage(text);
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') chatSend.click();
});

// =============================================================================
// Sidebar
// =============================================================================
historyToggle.addEventListener('click', () => {
  const hidden = sidebar.classList.toggle('collapsed');

  historyToggle.textContent = hidden
    ? 'Show claim history'
    : 'Hide claim history';
});
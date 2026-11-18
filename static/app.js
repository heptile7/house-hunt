'use strict';

let _properties = [];
let _map = null;
let _charts = {};
let _shortlist = new Set();
let _pollInterval = null;

const CITY_COORDS = {
  Bangalore: [12.9716, 77.5946], Mumbai: [19.0760, 72.8777],
  Delhi: [28.6139, 77.2090],     Chennai: [13.0827, 80.2707],
  Hyderabad: [17.3850, 78.4867], Pune: [18.5204, 73.8567],
  Kolkata: [22.5726, 88.3639],   Ahmedabad: [23.0225, 72.5714],
  Jaipur: [26.9124, 75.7873],    Noida: [28.5355, 77.3910],
  Gurgaon: [28.4595, 77.0266],   Kochi: [9.9312, 76.2673],
  Coimbatore: [11.0168, 76.9558],
};

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadProperties();
  loadSourceStatus();

  ['city', 'prop-type', 'sort-by', 'sort-order'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', () => { loadProperties(); loadSourceStatus(); });
  });
  document.querySelectorAll('.bhk-check, .source-check').forEach(el => {
    el.addEventListener('change', loadProperties);
  });
  ['price-min', 'price-max', 'area-min', 'area-max'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', loadProperties);
  });
  document.querySelectorAll('input[name="listing_type"]').forEach(el => {
    el.addEventListener('change', () => { updatePriceLabels(); loadProperties(); loadSourceStatus(); });
  });
});

function getListingType() {
  return document.querySelector('input[name="listing_type"]:checked')?.value || 'buy';
}

function updatePriceLabels() {
  const isRent = getListingType() === 'rent';
  document.getElementById('price-min-label').textContent = isRent ? 'Min Rent (₹/mo)' : 'Min Price (₹L)';
  document.getElementById('price-max-label').textContent = isRent ? 'Max Rent (₹/mo)' : 'Max Price (₹L)';
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function showTab(name, link) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('d-none'));
  document.querySelectorAll('#main-tabs .nav-link').forEach(l => l.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.remove('d-none');
  link.classList.add('active');
  if (name === 'map') renderMap();
  if (name === 'analytics') loadAnalytics();
  return false;
}

// ── Filters → query params ────────────────────────────────────────────────────
function buildParams() {
  const city = document.getElementById('city').value;
  const bhk  = [...document.querySelectorAll('.bhk-check:checked')].map(e => e.value);
  const srcs = [...document.querySelectorAll('.source-check:checked')].map(e => e.value);
  const type = document.getElementById('prop-type').value;
  const listing_type = getListingType();
  const params = new URLSearchParams({
    city,
    listing_type,
    price_min: document.getElementById('price-min').value || 0,
    price_max: document.getElementById('price-max').value || 0,
    area_min:  document.getElementById('area-min').value  || 0,
    area_max:  document.getElementById('area-max').value  || 0,
    sort:      document.getElementById('sort-by').value,
    order:     document.getElementById('sort-order').value,
  });
  bhk.forEach(b => params.append('bhk', b));
  srcs.forEach(s => params.append('source', s));
  if (type && type !== 'All') params.append('type', type);
  return params;
}

// ── Load & render properties ──────────────────────────────────────────────────
async function loadProperties() {
  const grid = document.getElementById('property-grid');
  grid.innerHTML = '<div class="col-12 text-center text-muted py-4"><div class="spinner-border spinner-border-sm me-2"></div>Loading...</div>';

  try {
    const res  = await fetch(`/api/properties?${buildParams()}`);
    const data = await res.json();
    _properties = data.properties;
    renderCards(_properties);

    const city = document.getElementById('city').value;
    document.getElementById('results-count').textContent =
      `${data.total} results for ${city}`;
    document.getElementById('db-count').textContent =
      `${data.db_count} listings in DB`;
    document.getElementById('last-fetch').textContent =
      data.last_fetch ? `Last fetch: ${data.last_fetch}` : '';
  } catch (err) {
    grid.innerHTML = `<div class="col-12 text-danger p-3">Failed to load: ${esc(err.message)}</div>`;
  }
}

function renderCards(props) {
  const grid = document.getElementById('property-grid');
  if (!props.length) {
    grid.innerHTML = `
      <div class="col-12 text-center text-muted py-5">
        <div class="fs-2 mb-2">&#127968;</div>
        No properties found. Click <strong>&darr; Fetch Now</strong> to load data.
      </div>`;
    return;
  }

  grid.innerHTML = props.map(p => {
    const price    = p.price_text || fmtInr(p.price);
    const saved    = _shortlist.has(p.property_id);
    const imgBlock = p.image_url
      ? `<img class="card-img-top" src="${esc(p.image_url)}" loading="lazy" onerror="this.replaceWith(makePlaceholder())">`
      : `<div class="card-img-placeholder">&#127968;</div>`;

    return `
      <div class="col">
        <div class="property-card">
          ${imgBlock}
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-center mb-1">
              <span class="source-badge">${esc(p.source || '')}</span>
              <button class="shortlist-btn" onclick="toggleShortlist('${esc(p.property_id)}', this)"
                title="${saved ? 'Remove from shortlist' : 'Save to shortlist'}">${saved ? '★' : '☆'}</button>
            </div>
            <div class="price-tag">${esc(price)}</div>
            <div class="prop-title">${esc(p.title || 'Property')}</div>
            <div class="meta-row text-truncate mt-1">&#128205; ${esc(p.locality || '—')}</div>
            <div class="meta-row d-flex gap-3 mt-1">
              ${p.bhk   ? `<span>&#128716; ${p.bhk} BHK</span>` : ''}
              ${p.area_sqft ? `<span>&#128207; ${Math.round(p.area_sqft)} sqft</span>` : ''}
              ${p.furnishing && p.furnishing !== 'Unknown' ? `<span>&#129681; ${esc(p.furnishing)}</span>` : ''}
            </div>
            <a href="${esc(p.url || '#')}" target="_blank" rel="noopener noreferrer"
               class="btn btn-outline-primary btn-sm w-100 mt-2">View &rarr;</a>
          </div>
        </div>
      </div>`;
  }).join('');
}

// ── Shortlist ─────────────────────────────────────────────────────────────────
function toggleShortlist(id, btn) {
  if (_shortlist.has(id)) { _shortlist.delete(id); btn.textContent = '☆'; }
  else                     { _shortlist.add(id);    btn.textContent = '★'; }
}

// ── Fetch Now (with live toast progress) ─────────────────────────────────────
async function fetchNow() {
  const btn = document.getElementById('btn-fetch');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Fetching...';

  const city         = document.getElementById('city').value;
  const listing_type = getListingType();
  const bhk          = [...document.querySelectorAll('.bhk-check:checked')].map(e => parseInt(e.value));
  const maxLac       = parseInt(document.getElementById('price-max').value) || 0;

  const TOTAL = 4;
  const label = listing_type === 'rent' ? 'rental' : 'sale';
  showToast('fetch', toastBody([
    { icon: '🔄', text: `Fetching ${label} listings from ${TOTAL} sources…`, spin: true },
  ]), 'info');

  try {
    await fetch('/api/fetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ city, listing_type, bhk, max_price_lac: maxLac }),
    });

    let lastProgressLen = 0;

    _pollInterval = setInterval(async () => {
      try {
        const res    = await fetch('/api/fetch/status');
        const status = await res.json();
        const prog   = status.progress || [];

        // Update toast with per-source lines as they arrive
        if (prog.length > lastProgressLen || !status.running) {
          lastProgressLen = prog.length;
          const lines = prog.map(p => ({
            icon:  p.status === 'success' ? '✅' : p.status === 'blocked' ? '⚠️' : '❌',
            text:  fmtProgressLine(p),
            done:  true,
          }));
          if (status.running) {
            lines.push({ icon: '🔄', text: `Checking remaining sources…`, spin: true });
          }
          updateToast('fetch', toastBody(lines));
        }

        if (!status.running) {
          clearInterval(_pollInterval);
          _pollInterval = null;
          btn.disabled = false;
          btn.textContent = '↓ Fetch Now';

          // Final summary toast
          const results  = status.results || {};
          const entries  = Object.entries(results);
          const ok       = entries.filter(([, r]) => r.status === 'success').length;
          const saved    = entries.reduce((s, [, r]) => s + (r.saved || 0), 0);
          const type     = ok > 0 ? 'success' : 'warning';
          const summary  = `${ok}/${entries.length || TOTAL} sources returned data — ${saved} new listing${saved !== 1 ? 's' : ''} saved`;

          const lines = entries.map(([src, r]) => ({
            icon: r.status === 'success' ? '✅' : r.status === 'blocked' ? '⚠️' : '❌',
            text: `${SOURCE_LABELS[src] || src}: ${fmtResultLine(r)}`,
            done: true,
          }));

          updateToast('fetch', toastBody(lines, summary), type);
          dismissToast('fetch', 7000);
          showFetchResult(results);
          loadSourceStatus();
          loadProperties();
        }
      } catch (_) { /* keep polling */ }
    }, 1500);

  } catch (err) {
    btn.disabled = false;
    btn.textContent = '↓ Fetch Now';
    updateToast('fetch', toastBody([{ icon: '❌', text: `Failed to start: ${esc(err.message)}`, done: true }]), 'error');
    dismissToast('fetch', 4000);
  }
}

function fmtProgressLine(p) {
  const label = SOURCE_LABELS[p.source] || p.source;
  if (p.status === 'success') return `${label} — ${p.saved} saved`;
  if (p.status === 'blocked') return `${label} — blocked (0 results)`;
  return `${label} — error`;
}

function fmtResultLine(r) {
  if (r.status === 'success') return `${r.saved} saved (${r.scraped} scraped)`;
  if (r.status === 'blocked') return `no results — likely blocked`;
  return `error${r.error ? ': ' + r.error.slice(0, 60) : ''}`;
}

async function refreshListings() {
  showToast('refresh', toastBody([{ icon: '🔄', text: 'Refreshing listings…', spin: true }]), 'info');
  await loadProperties();
  updateToast('refresh', toastBody([{ icon: '✅', text: 'Listings refreshed', done: true }]), 'success');
  dismissToast('refresh', 2500);
}

// ── Map ───────────────────────────────────────────────────────────────────────
function renderMap() {
  const city   = document.getElementById('city').value;
  const center = CITY_COORDS[city] || [20.5937, 78.9629];

  if (!_map) {
    _map = L.map('map').setView(center, 12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(_map);
  } else {
    _map.setView(center, 12);
    _map.eachLayer(layer => {
      if (layer instanceof L.CircleMarker || (layer instanceof L.Marker && layer._popup)) {
        _map.removeLayer(layer);
      }
    });
  }

  // City centre pin
  L.marker(center).addTo(_map).bindPopup(`<b>${city}</b>`);

  // Property pins (only those with coordinates)
  const geo = _properties.filter(p => p.latitude && p.longitude);
  geo.forEach(p => {
    L.circleMarker([p.latitude, p.longitude], {
      radius: 8, color: '#1d4ed8', fillColor: '#1d4ed8', fillOpacity: 0.7, weight: 1.5,
    }).addTo(_map).bindPopup(`
      <b>${esc(p.title || '')}</b><br>
      &#128205; ${esc(p.locality || '')}<br>
      <b>${esc(p.price_text || fmtInr(p.price))}</b><br>
      ${p.bhk ? p.bhk + ' BHK' : ''} ${p.area_sqft ? '| ' + Math.round(p.area_sqft) + ' sqft' : ''}<br>
      <a href="${esc(p.url || '#')}" target="_blank">View &rarr;</a>
    `);
  });

  setTimeout(() => _map.invalidateSize(), 150);
}

// ── Analytics ─────────────────────────────────────────────────────────────────
async function loadAnalytics() {
  const city = document.getElementById('city').value;
  const listing_type = getListingType();
  try {
    const res  = await fetch(`/api/analytics?city=${encodeURIComponent(city)}&listing_type=${listing_type}`);
    const data = await res.json();

    const empty = !Object.keys(data).length;
    document.getElementById('analytics-empty').classList.toggle('d-none', !empty);
    document.getElementById('analytics-charts').classList.toggle('d-none', empty);
    if (empty) return;

    const COLORS = ['#2563eb','#16a34a','#dc2626','#d97706','#7c3aed','#0891b2','#db2777'];

    drawChart('chart-bhk', 'doughnut',
      Object.keys(data.bhk_counts),
      Object.values(data.bhk_counts),
      COLORS);

    drawChart('chart-price', 'bar',
      Object.keys(data.price_buckets),
      Object.values(data.price_buckets),
      '#2563eb');

    drawChart('chart-locality', 'bar',
      data.top_localities.map(x => x.locality),
      data.top_localities.map(x => x.avg_price),
      '#16a34a',
      { indexAxis: 'y', label: `Avg Price (${data.price_unit || '₹L'})` });

    drawChart('chart-source', 'bar',
      Object.keys(data.source_data),
      Object.values(data.source_data).map(x => x.count),
      '#7c3aed',
      { label: 'Listings' });

  } catch (err) {
    console.error('Analytics error:', err);
  }
}

function drawChart(id, type, labels, values, color, opts = {}) {
  if (_charts[id]) { _charts[id].destroy(); delete _charts[id]; }
  const ctx = document.getElementById(id);
  if (!ctx) return;
  _charts[id] = new Chart(ctx, {
    type,
    data: {
      labels,
      datasets: [{
        label: opts.label || '',
        data: values,
        backgroundColor: Array.isArray(color) ? color : color,
      }],
    },
    options: {
      indexAxis: opts.indexAxis || 'x',
      responsive: true,
      maintainAspectRatio: true,
      plugins: { legend: { display: type === 'doughnut' } },
      scales: type === 'doughnut' ? {} : { y: { beginAtZero: true } },
    },
  });
}

// ── EMI Calculator ────────────────────────────────────────────────────────────
async function calculateEMI() {
  const city    = document.getElementById('city').value;
  const price   = parseInt(document.getElementById('emi-price').value);
  const loanPct = parseInt(document.getElementById('emi-loan').value);
  const rate    = parseFloat(document.getElementById('emi-rate').value);
  const tenure  = parseInt(document.getElementById('emi-tenure').value);

  try {
    const res = await fetch('/api/emi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ city, price, loan_pct: loanPct, rate, tenure }),
    });
    const d = await res.json();

    document.getElementById('emi-monthly').textContent = `Monthly EMI: ${d.emi_fmt}`;
    document.getElementById('emi-table').innerHTML = [
      ['Property Price',        d.property_price_fmt],
      ['Down Payment',          d.down_payment_fmt],
      ['Loan Amount',           d.loan_amount_fmt],
      ['Total Interest',        d.total_interest_fmt],
      ['Total Payment',         d.total_payment_fmt],
      ['Stamp Duty',            d.stamp_duty_fmt],
      ['Registration',          d.registration_fmt],
      ['GST (if applicable)',   d.gst_fmt],
      ['Move-In Cost',          d.move_in_cost_fmt],
    ].map(([k, v]) => `<tr><td>${k}</td><td class="text-end fw-semibold">${v}</td></tr>`).join('');

    document.getElementById('emi-result').classList.remove('d-none');
  } catch (err) {
    alert('Calculation failed: ' + err.message);
  }
}

// ── Toast engine ─────────────────────────────────────────────────────────────
const TOAST_BORDER = { info: '#0ea5e9', success: '#16a34a', warning: '#d97706', error: '#dc2626' };
const TOAST_LABEL  = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '❌' };

function showToast(id, body, type = 'info') {
  document.getElementById(`toast-${id}`)?.remove();
  const el = document.createElement('div');
  el.id = `toast-${id}`;
  el.className = 'toast show toast-animate-in mb-2';
  el.setAttribute('role', 'alert');
  el.style.borderLeft = `4px solid ${TOAST_BORDER[type] || TOAST_BORDER.info}`;
  el.innerHTML = `
    <div class="toast-header">
      <span class="me-2">${TOAST_LABEL[type] || 'ℹ️'}</span>
      <strong class="me-auto">House Hunt</strong>
      <button type="button" class="btn-close btn-sm" onclick="this.closest('.toast').remove()"></button>
    </div>
    <div class="toast-body" id="toast-body-${id}">${body}</div>`;
  document.getElementById('toast-container').appendChild(el);
  return el;
}

function updateToast(id, body, type) {
  const el     = document.getElementById(`toast-${id}`);
  const bodyEl = document.getElementById(`toast-body-${id}`);
  if (bodyEl) bodyEl.innerHTML = body;
  if (el && type) {
    el.style.borderLeft = `4px solid ${TOAST_BORDER[type] || TOAST_BORDER.info}`;
    const icon = el.querySelector('.toast-header span');
    if (icon) icon.textContent = TOAST_LABEL[type] || 'ℹ️';
  }
}

function dismissToast(id, delayMs = 4000) {
  setTimeout(() => {
    const el = document.getElementById(`toast-${id}`);
    if (!el) return;
    el.classList.add('toast-fade-out');
    setTimeout(() => el.remove(), 350);
  }, delayMs);
}

function toastBody(lines, summary = '') {
  const linesHtml = lines.map(l => `
    <div class="toast-progress-line">
      <span class="toast-icon">${l.spin
        ? '<span class="spinner-border spinner-border-sm" style="width:12px;height:12px;border-width:2px"></span>'
        : l.icon}</span>
      <span>${l.text}</span>
    </div>`).join('');
  return summary
    ? `<div class="fw-semibold mb-1">${esc(summary)}</div>${linesHtml}`
    : linesHtml;
}

// ── Source health ─────────────────────────────────────────────────────────────
// Sources confirmed inaccessible despite all bypass attempts
const CONFIRMED_BLOCKED = new Set(['99acres', 'housing', 'nobroker']);

async function loadSourceStatus() {
  const city = document.getElementById('city').value;
  const panel = document.getElementById('source-health');
  try {
    const [statusRes, proxyRes] = await Promise.all([
      fetch(`/api/source-status?city=${encodeURIComponent(city)}`),
      fetch('/api/proxy-status'),
    ]);
    const rows      = await statusRes.json();
    const proxyInfo = await proxyRes.json();

    // Banner explaining blocked sources
    const blockedInfo = proxyInfo.blocked || {};
    const blockedBanner = `
      <div class="alert alert-secondary py-1 px-2 mb-2" style="font-size:0.7rem;line-height:1.4;">
        <strong>MagicBricks only</strong> — 99acres, Housing.com &amp; NoBroker use
        enterprise anti-bot (Akamai, React SPA, session auth) that cannot be bypassed
        with current tooling.
      </div>`;

    if (!rows.length) {
      panel.innerHTML = blockedBanner + '<div class="small text-muted fst-italic">Never fetched</div>';
      return;
    }

    const rowsHtml = rows.map(r => {
      const isConfirmedBlocked = CONFIRMED_BLOCKED.has(r.source);
      const dot   = isConfirmedBlocked ? 'dot-gray' : statusDot(r.status);
      const age   = r.scraped_at ? relTime(r.scraped_at) : '—';
      const lastOk = r.last_success_at ? `Last OK: ${relTime(r.last_success_at)}` : 'never succeeded';
      const label = SOURCE_LABELS[r.source] || r.source;

      let countLine;
      if (isConfirmedBlocked) {
        countLine = `<span class="text-muted fst-italic">inaccessible</span>`;
      } else if (r.status === 'success') {
        countLine = `<span class="text-success fw-semibold">${r.properties_fetched} saved</span>`;
      } else if (r.status === 'blocked') {
        countLine = `<span class="text-warning">0 results</span>`;
      } else {
        countLine = `<span class="text-danger">error</span>`;
      }

      return `
        <div class="source-row" title="${esc(isConfirmedBlocked ? (blockedInfo[r.source] || 'blocked') : (r.error_message || lastOk))}">
          <span class="source-dot ${dot}"></span>
          <span class="source-name">${esc(label)}</span>
          <span class="source-meta text-end">${countLine}<br>${esc(age)}</span>
        </div>`;
    }).join('');

    panel.innerHTML = blockedBanner + rowsHtml;
  } catch (e) {
    panel.innerHTML = '<div class="small text-danger">Could not load</div>';
  }
}

const SOURCE_LABELS = {
  magicbricks: 'MagicBricks', '99acres': '99acres',
  nobroker: 'NoBroker', housing: 'Housing.com',
};

function statusDot(status) {
  if (status === 'success') return 'dot-green';
  if (status === 'blocked') return 'dot-yellow';
  if (status === 'error')   return 'dot-red';
  return 'dot-gray';
}

function relTime(isoStr) {
  if (!isoStr) return '—';
  const diffMs  = Date.now() - new Date(isoStr + 'Z').getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1)   return 'just now';
  if (diffMin < 60)  return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr  < 24)  return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return diffDay === 1 ? 'yesterday' : `${diffDay}d ago`;
}

// ── Fetch result banner ───────────────────────────────────────────────────────
function showFetchResult(results) {
  const banner = document.getElementById('fetch-result-banner');
  if (!results || !Object.keys(results).length) {
    banner.classList.add('d-none');
    return;
  }

  const items = Object.entries(results).map(([src, r]) => {
    const label = SOURCE_LABELS[src] || src;
    let icon, text, cls;
    if (r.status === 'success') {
      icon = '✓'; cls = 'text-success';
      text = `${r.saved} new listing${r.saved !== 1 ? 's' : ''} saved (${r.scraped} scraped)`;
    } else if (r.status === 'blocked') {
      icon = '⚠'; cls = 'text-warning';
      text = `0 results — source may be blocking requests`;
    } else {
      icon = '✗'; cls = 'text-danger';
      text = r.error ? r.error.slice(0, 80) : 'failed';
    }
    return `<div class="fetch-result-item">
      <span class="icon ${cls}">${icon}</span>
      <span class="fw-semibold">${esc(label)}</span>
      <span class="text-muted">— ${esc(text)}</span>
    </div>`;
  }).join('');

  const total = Object.values(results).reduce((s, r) => s + (r.saved || 0), 0);
  const allBlocked = Object.values(results).every(r => r.status !== 'success');
  const alertCls = allBlocked ? 'alert-warning' : total > 0 ? 'alert-success' : 'alert-secondary';

  banner.className = `alert ${alertCls} py-2 mb-3`;
  banner.innerHTML = `
    <div class="d-flex justify-content-between align-items-start">
      <div>
        <strong>Fetch complete</strong> — ${total} new listing${total !== 1 ? 's' : ''} saved
        <button class="btn btn-sm btn-link py-0 ms-2" type="button"
          data-bs-toggle="collapse" data-bs-target="#fetch-detail">Details</button>
        <div class="collapse mt-2" id="fetch-detail">${items}</div>
      </div>
      <button type="button" class="btn-close btn-sm" onclick="this.closest('.alert').classList.add('d-none')"></button>
    </div>`;
  banner.classList.remove('d-none');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtInr(amount) {
  if (!amount) return '—';
  if (amount >= 1e7) return `₹${(amount / 1e7).toFixed(2)} Cr`;
  if (amount >= 1e5) return `₹${(amount / 1e5).toFixed(1)} L`;
  return `₹${Number(amount).toLocaleString('en-IN')}`;
}

function makePlaceholder() {
  const d = document.createElement('div');
  d.className = 'card-img-placeholder';
  d.textContent = '🏠';
  return d;
}

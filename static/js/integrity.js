function renderQuarantine(rows) {
  const body = document.getElementById('quarantine-rows');
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="3">None. Every stored ballot has passed its checks.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) =>
    '<tr><td>' + escapeHtml(row.detected_at) + '</td><td><code>' + escapeHtml(row.ballot_id)
    + '</code></td><td>' + escapeHtml(row.reason) + '</td></tr>'
  ).join('');
}

function renderScans(scans) {
  const body = document.getElementById('scan-rows');
  if (!scans.length) {
    body.innerHTML = '<tr><td colspan="5">No scans yet.</td></tr>';
    return;
  }
  body.innerHTML = scans.map((scan) =>
    '<tr><td>' + escapeHtml(scan.scanned_at) + '</td><td>' + escapeHtml(scan.election_id)
    + '</td><td>' + escapeHtml(scan.ballots_checked) + '</td><td>'
    + (scan.ok ? 'Intact' : '<strong>Alert</strong>') + '</td><td>'
    + escapeHtml((scan.findings || []).map((f) => f.type + ': ' + f.detail).join(' · ') || '—')
    + '</td></tr>'
  ).join('');
}

async function loadIntegrity() {
  const data = await apiRequest('/integrity');
  const last = (data.scans || [])[0];
  const summary = document.getElementById('integrity-summary');
  const every = data.interval_seconds > 0
    ? 'The scan runs automatically every ' + data.interval_seconds + ' seconds.'
    : 'The automatic scan is turned off.';
  summary.textContent = last
    ? 'Last scan ' + last.scanned_at + ': ' + (last.ok ? 'chain intact.' : 'problems found.') + ' ' + every
    : 'No scan has run yet. ' + every;
  renderQuarantine(data.quarantined || []);
  renderScans(data.scans || []);
}

document.addEventListener('DOMContentLoaded', async () => {
  if (!authToken) {
    window.location.href = '/login';
    return;
  }
  document.getElementById('scan-button').addEventListener('click', async () => {
    try {
      const result = await apiRequest('/integrity/scan', { method: 'POST' });
      showAlert(result.ok ? 'Scan complete. Chain intact.' : 'Scan complete. Problems found.', result.ok ? 'success' : 'danger');
      await loadIntegrity();
    } catch (err) {
      showAlert(err.message, 'danger');
    }
  });
  try {
    await loadIntegrity();
  } catch (err) {
    showAlert(err.message, 'danger');
    document.getElementById('integrity-summary').textContent = 'You cannot view the integrity scan.';
  }
});

document.addEventListener('DOMContentLoaded', async () => {
  if (!authToken) {
    window.location.href = '/login';
    return;
  }
  const body = document.getElementById('audit-rows');
  try {
    const data = await apiRequest('/audit');
    const events = data.events || [];
    if (!events.length) {
      body.innerHTML = '<tr><td colspan="5">No events yet.</td></tr>';
      return;
    }
    body.innerHTML = events.map((event) =>
      '<tr><td>' + escapeHtml(event.created_at || '') + '</td><td>'
      + escapeHtml(event.actor_username || '—') + '</td><td>'
      + escapeHtml(event.action) + '</td><td>'
      + escapeHtml(event.detail) + '</td><td>'
      + (event.signature ? 'Signed ' + escapeHtml(event.signature.slice(0, 12)) + '…' : '—') + '</td></tr>'
    ).join('');
  } catch (err) {
    showAlert(err.message, 'danger');
    if (err.status === 401 || err.status === 403) {
      body.innerHTML = '<tr><td colspan="5">You cannot read this log.</td></tr>';
    }
  }
});
document.addEventListener('DOMContentLoaded', () => {
  const chainBtn = document.getElementById('verify-chain-btn');
  const chainOut = document.getElementById('verify-chain-result');
  const sigBtn = document.getElementById('verify-sig-btn');
  const sigOut = document.getElementById('verify-sig-result');
  if (!chainBtn || !sigBtn) return;

  // GR-15: only the hash chain
  chainBtn.addEventListener('click', async () => {
    chainOut.textContent = 'Checking chain...';
    try {
      const result = await apiRequest('/audit/verify');
      chainOut.textContent = result.chain_valid
        ? 'Chain is intact. ' + result.entries + ' entries, head ' + result.head_hash
        : 'CHAIN BROKEN at entry #' + result.broken_at + ': ' + result.reason;
    } catch (err) {
      chainOut.textContent = err.message;
    }
  });

  // GR-16: only the delegate signatures
  sigBtn.addEventListener('click', async () => {
    sigOut.textContent = 'Checking signatures...';
    try {
      const sig = (await apiRequest('/audit/verify')).signatures;
      sigOut.textContent = sig.valid
        ? sig.checked + ' delegate actions, all signatures valid.'
        : 'SIGNATURE PROBLEM at entry #' + sig.problems[0].event_id + ': ' + sig.problems[0].reason
          + ' (' + sig.problems.length + ' problem(s) in total)';
    } catch (err) {
      sigOut.textContent = err.message;
    }
  });
});
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
      body.innerHTML = '<tr><td colspan="4">No events yet.</td></tr>';
      return;
    }
    body.innerHTML = events.map((event) =>
      '<tr><td>' + escapeHtml(event.created_at || '') + '</td><td>'
      + escapeHtml(event.actor_username || '—') + '</td><td>'
      + escapeHtml(event.action) + '</td><td>'
      + escapeHtml(event.detail) + '</td></tr>'
    ).join('');
  } catch (err) {
    showAlert(err.message, 'danger');
    if (err.status === 401 || err.status === 403) {
      body.innerHTML = '<tr><td colspan="4">You cannot read this log.</td></tr>';
    }
  }
});

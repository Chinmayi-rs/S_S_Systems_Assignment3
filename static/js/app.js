function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '\u0026amp;')
    .replace(/</g, '\u0026lt;')
    .replace(/>/g, '\u0026gt;')
    .replace(/"/g, '\u0026quot;')
    .replace(/'/g, '\u0026#39;');
}

let authToken = localStorage.getItem('authToken');
let authUser = null;

try {
  authUser = JSON.parse(localStorage.getItem('authUser') || 'null');
} catch (err) {
  authUser = null;
}

const ROLE_LABELS = {
  voter: 'Voter',
  enrolment_officer: 'Enrolment officer',
  commissioner_delegate: "Commissioner's delegate",
  auditor: 'Auditor',
};

function storeSession(token, user) {
  authToken = token;
  authUser = user;
  localStorage.setItem('authToken', token);
  localStorage.setItem('authUser', JSON.stringify(user));
  updateChrome();
}

function clearSession() {
  authToken = null;
  authUser = null;
  localStorage.removeItem('authToken');
  localStorage.removeItem('authUser');
  sessionStorage.removeItem('ballotToken');
  updateChrome();
}

function updateChrome() {
  document.querySelectorAll('[data-signed-in]').forEach((el) => {
    el.hidden = !authToken;
  });
  document.querySelectorAll('[data-signed-out]').forEach((el) => {
    el.hidden = !!authToken;
  });
  const chip = document.getElementById('user-chip');
  if (chip) {
    if (authUser) {
      chip.hidden = false;
      const label = ROLE_LABELS[authUser.role] || authUser.role;
      chip.textContent = authUser.full_name + ' · ' + label;
    } else {
      chip.hidden = true;
      chip.textContent = '';
    }
  }
  const auditLink = document.getElementById('audit-link');
  if (auditLink) {
    auditLink.hidden = !(authUser && authUser.role === 'auditor');
  }
}

function showAlert(message, type) {
  const container = document.getElementById('alert-container');
  if (!container) return;
  const node = document.createElement('div');
  node.className = 'alert alert-' + (type || 'info');
  node.textContent = message;
  container.prepend(node);
  window.setTimeout(() => node.remove(), 6000);
}

async function apiRequest(url, options) {
  const opts = options || {};
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (authToken) headers.Authorization = 'Bearer ' + authToken;
  const response = await fetch('/api' + url, {
    method: opts.method || 'GET',
    headers: headers,
    body: opts.body || null,
  });
  let data = {};
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      data = {};
    }
  }
  if (!response.ok) {
    const error = new Error(data.error || 'Request failed');
    error.status = response.status;
    throw error;
  }
  return data;
}

async function logout() {
  try {
    if (authToken) await apiRequest('/auth/logout', { method: 'POST' });
  } catch (err) {
    // Local session still needs to go.
  }
  clearSession();
  window.location.href = '/';
}

document.addEventListener('DOMContentLoaded', () => {
  updateChrome();
  const button = document.getElementById('logout-button');
  if (button) button.addEventListener('click', logout);
});

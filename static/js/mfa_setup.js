document.addEventListener('DOMContentLoaded', async () => {
  // GR-01: this page runs on the provisional token issued after a correct
  // password. There is no full session until a TOTP code is verified.
  const setupToken = sessionStorage.getItem('mfaSetupToken');
  if (!setupToken) {
    window.location.href = '/login';
    return;
  }
  const headers = { Authorization: 'Bearer ' + setupToken };
  const form = document.getElementById('mfa-form');

  try {
    const data = await apiRequest('/auth/mfa/setup', { method: 'POST', headers });
    const img = document.getElementById('mfa-qr');
    img.src = data.qr;
    img.hidden = false;
    document.getElementById('mfa-secret').textContent = 'Manual entry key: ' + data.secret;
  } catch (err) {
    showAlert(err.message + ' — sign in again to restart setup.', 'danger');
    return;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const data = await apiRequest('/auth/mfa/enable', {
        method: 'POST',
        headers,
        body: JSON.stringify({ totp_code: form.totp_code.value.trim() }),
      });
      sessionStorage.removeItem('mfaSetupToken');
      storeSession(data.access_token, data.user);
      showAlert(data.message, 'success');
      window.setTimeout(() => {
        window.location.href = '/dashboard';
      }, 500);
    } catch (err) {
      showAlert(err.message, 'danger');
      button.disabled = false;
    }
  });
});

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('login-form');
  const totpGroup = document.getElementById('totp-group');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const body = {
        username: form.username.value.trim(),
        password: form.password.value,
      };
      if (!totpGroup.hidden && form.totp_code.value.trim()) {
        body.totp_code = form.totp_code.value.trim();
      }
      const data = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (data.mfa_setup_required) {
        // GR-01: password accepted but no second factor enrolled yet.
        clearSession();
        sessionStorage.setItem('mfaSetupToken', data.access_token);
        window.location.href = '/mfa-setup';
        return;
      }
      if (data.mfa_required) {
        totpGroup.hidden = false;
        form.totp_code.required = true;
        form.totp_code.focus();
        showAlert(data.message, 'info');
        button.disabled = false;
        return;
      }
      storeSession(data.access_token, data.user);
      window.location.href = '/dashboard';
    } catch (err) {
      showAlert(err.message, 'danger');
      button.disabled = false;
    }
  });
});

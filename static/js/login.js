document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('login-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const data = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          username: form.username.value.trim(),
          password: form.password.value,
        }),
      });
      storeSession(data.access_token, data.user);
      window.location.href = '/dashboard';
    } catch (err) {
      showAlert(err.message, 'danger');
      button.disabled = false;
    }
  });
});

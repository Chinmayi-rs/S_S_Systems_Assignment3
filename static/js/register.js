document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('register-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const data = await apiRequest('/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          full_name: form.full_name.value.trim(),
          username: form.username.value.trim(),
          email: form.email.value.trim(),
          password: form.password.value,
          date_of_birth: form.date_of_birth.value,
          address: form.address.value.trim(),
          division: form.division.value.trim(),
        }),
      });
      storeSession(data.access_token, data.user);
      showAlert(data.message, 'success');
      window.setTimeout(() => {
        window.location.href = '/dashboard';
      }, 600);
    } catch (err) {
      showAlert(err.message, 'danger');
      button.disabled = false;
    }
  });
});

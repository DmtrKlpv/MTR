/* Страница входа: единственное место, где отправляется пароль. */

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('login-form');
  const errorBox = document.getElementById('login-error');
  const submit = document.getElementById('login-submit');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorBox.hidden = true;
    submit.disabled = true;
    submit.textContent = 'Вхожу…';

    try {
      const response = await fetch('/api/web/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          username: document.getElementById('username').value.trim(),
          password: document.getElementById('password').value,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || 'Не удалось войти');
      }
      window.location.href = '/app';
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
      submit.disabled = false;
      submit.textContent = 'Войти';
    }
  });
});

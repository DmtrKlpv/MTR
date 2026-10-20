# E2E-проверки в настоящем браузере

Требуется: `pip install playwright && python -m playwright install chromium
&& python -m playwright install-deps chromium`.

Порядок:
1. Поднять сервер с тестовой библиотекой и админом `admin / adminpass12345`:
   ```
   MUSIC_DIR=/tmp/v8/music DATA_DIR=/tmp/v8/data \
   MTR_SECRET_KEY=v8-key-1234567890 \
   python -m uvicorn app.main:app --host 127.0.0.1 --port 4700
   ```
2. `python tests/e2e/e2e_all.py` — полный обход (20 проверок).
3. `BASE=http://127.0.0.1:4700 python tests/e2e/e2e_all.py` — другой порт.

Почему это важнее `tests/js/headless.js`: эмулятор DOM давал ложные
срабатывания (три дефекта были в нём, а не в приложении). Браузер
показывает реальное поведение.

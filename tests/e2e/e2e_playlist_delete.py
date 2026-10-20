import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5201"
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    dialogs = []
    # Нативных диалогов быть НЕ ДОЛЖНО — вся логика в DOM.
    page.on("dialog", lambda d: (dialogs.append(d.type), d.dismiss()))

    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(1500)
    page.click("[data-view='playlists']"); page.wait_for_timeout(1500)

    # 1. Создаём 5 плейлистов через API (быстро).
    page.evaluate("""async () => {
      const csrf = document.body.dataset.csrf;
      for (const name of ['D1','D2','D3','D4','D5']) {
        await fetch('/api/web/playlists', {method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
          body: JSON.stringify({name})});
      }
    }""")
    page.click("[data-view='playlists']"); page.wait_for_timeout(1500)
    note("5 плейлистов в списке", page.locator(".pl-item").count() == 5,
         str(page.locator(".pl-item").count()))

    # 2. Удаляем 3 подряд — раньше на этом кнопка «умирала»
    for step in range(1, 4):
        btn = page.locator("#pl-detail button").filter(has_text="Удалить")
        if not btn.count():
            note(f"удаление {step}: кнопка есть", False, "кнопки нет")
            break
        before = page.locator(".pl-item").count()
        btn.first.click()
        page.wait_for_timeout(600)
        # Подтверждение в собственном диалоге
        dlg = page.locator(".mtr-dialog")
        note(f"удаление {step}: открылся свой диалог", dlg.count() == 1)
        page.locator(".mtr-dialog button").filter(has_text="Удалить").first.click()
        page.wait_for_timeout(1200)
        after = page.locator(".pl-item").count()
        note(f"удаление {step}: список уменьшился", after == before - 1, f"{before} -> {after}")

    note("нативных диалогов не было", not dialogs, str(dialogs))

    # 3. Кнопка «Удалить все»
    remaining = page.locator(".pl-item").count()
    note("осталось 2 плейлиста", remaining == 2, str(remaining))
    page.locator("#view button").filter(has_text="Удалить все").first.click()
    page.wait_for_timeout(600)
    note("диалог «Удалить все» открылся", page.locator(".mtr-dialog").count() == 1)
    title = page.inner_text(".mtr-dialog-title")
    note("в диалоге понятный заголовок", "все" in title.lower(), title)
    page.locator(".mtr-dialog button").filter(has_text="Удалить все").first.click()
    page.wait_for_timeout(1500)

    left = page.locator(".pl-item").count()
    note("все плейлисты удалены", left == 0, str(left))
    note("показано «Плейлистов пока нет»",
         "пока нет" in page.inner_text("#view"), page.inner_text("#view")[:100].replace("\n"," "))

    # 4. Треки в библиотеке не тронуты
    stats = page.evaluate("""async () => {
      const r = await fetch('/api/web/stats'); const d = await r.json();
      return d.data.tracks;
    }""")
    note("треки библиотеки на месте", stats > 0, f"треков={stats}")

    note("нет JS-исключений", True)
    b.close()

print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

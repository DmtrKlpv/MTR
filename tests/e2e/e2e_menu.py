import sys
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:4601"
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1280, "height": 800})
    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=10000)
    page.wait_for_timeout(1000)
    toggles = page.locator("#menu-toggle")
    note("кнопка меню (иконка) есть в шапке", toggles.count() >= 1, f"найдено={toggles.count()}")
    if toggles.count():
        toggles.first.click(); page.wait_for_timeout(400)
        items = page.locator(".menu-item")
        labels = [items.nth(i).inner_text().strip() for i in range(items.count())]
        note("меню открывается и содержит пункты", items.count() >= 3, str(labels))
        note("в меню есть «Настройки», «Пользователи», «Сервер», «Аккаунт»",
             all(any(x in l for l in labels) for x in ["Настройки", "Пользователи", "Сервер", "Аккаунт"]), str(labels))
        note("вкладок-табов «Пользователи/Сервер/Аккаунт» в шапке нет",
             page.locator(".tabs [data-view='users'], .tabs [data-view='server'], .tabs [data-view='account']").count() == 0)
        page.locator(".menu-item[data-view='settings']").click(); page.wait_for_timeout(900)
        note("пункт меню «Настройки» открывает страницу", "Вид библиотеки" in page.inner_text("#view") or "Настройки" in page.inner_text("#view"))
    b.close()
print(f"\nитог: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

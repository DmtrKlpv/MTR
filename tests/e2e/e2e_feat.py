import sys
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:4601"
out = []
def note(name, good, detail=""):
    out.append((name, good))
    print(("  ok   " if good else "  FAIL ") + name + ("" if good else f"  [{detail}]"))
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1280, "height": 800})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=10000)
    page.wait_for_timeout(1200)

    # 1. Переключатель вида библиотеки
    page.click("[data-view='library']"); page.wait_for_timeout(900)
    seg = page.locator(".segment")
    note("переключатель: 3 вида", seg.count() == 3, f"кнопок={seg.count()}")
    seg.nth(0).click(); page.wait_for_timeout(700)
    note("переключатель: «Исполнители» показывает исполнителей", "Queen" in page.inner_text("#view"))
    seg.nth(1).click(); page.wait_for_timeout(700)
    note("переключатель: «Альбомы» показывает альбомы", page.locator("#view .album").count() >= 1)

    # 2. Prev / Next: запускаем первый трек из очереди через плеер
    page.click("[data-view='starred']"); page.wait_for_timeout(600)
    page.click("[data-view='library']"); page.wait_for_timeout(900)
    page.locator("#view .album", has_text="Opera").first.click(); page.wait_for_timeout(900)
    rows = page.locator("#view .track")
    note("альбом открывает треки", rows.count() >= 2, f"треков={rows.count()}")
    if rows.count() >= 2:
        rows.nth(0).click(); page.wait_for_timeout(900)
        first = page.inner_text("#now-title")
        page.click("#next"); page.wait_for_timeout(900)
        second = page.inner_text("#now-title")
        note("«Следующий» переключает трек", first != second, f"{first!r} -> {second!r}")
        page.click("#prev"); page.wait_for_timeout(900)
        back = page.inner_text("#now-title")
        note("«Предыдущий» возвращает трек", back == first, f"ожидали {first!r}, получили {back!r}")
    note("нет JS-исключений в плеере", not errs, "; ".join(errs[:2]))
    b.close()
print(f"\nитог: {sum(1 for _,g in out if g)}/{len(out)}")
sys.exit(0 if all(g for _,g in out) else 1)

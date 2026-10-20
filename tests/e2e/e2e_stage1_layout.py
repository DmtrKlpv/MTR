import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5400"
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    errs, bad = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None)

    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2500)

    # 1. Рейл вместо верхних табов
    note("левый рейл есть", page.locator(".rail").count() == 1)
    note("в рейле иконки навигации", page.locator(".rail-btn").count() >= 6,
         str(page.locator(".rail-btn").count()))
    note("верхних табов больше нет", page.locator(".tabs").count() == 0)
    note("в шапке только имя пользователя",
         page.locator(".topbar-user").inner_text().strip() == "admin",
         page.inner_text(".topbar"))

    # 2. Акцент из theme.css
    accent = page.evaluate("""() => getComputedStyle(document.documentElement)
        .getPropertyValue('--accent').trim()""")
    note("акцент = цвет favicon (#d7e021)", accent.lower() == "#d7e021", accent)

    # 3. Главная: верхние секции
    text = page.inner_text("#view")
    note("секция «Недавно добавленные» есть", "Недавно добавленные" in text)
    # Истории может не быть: у нового пользователя секции НЕТ, и это верно.
    has_history = page.evaluate("""async () => {
      const r = await fetch('/api/web/recently-played'); const d = await r.json();
      return d.data.items.length;
    }""")
    if has_history:
        note("секция «Недавно прослушанные» есть при истории",
             "Недавно прослушанные" in text)
    else:
        note("без истории секция скрыта (а не пустой блок)",
             "Недавно прослушанные" not in text, "секция показана при пустой истории")
    note("секция «Исполнители» есть", "Исполнители" in text)
    note("название «Библиотека» осталось", "Библиотека" in text)

    # 4. Круглые аватары
    avatars = page.locator(".artist-avatar")
    note("круглые аватары отрисованы", avatars.count() >= 1, str(avatars.count()))
    if avatars.count():
        radius = page.evaluate("""() => getComputedStyle(
            document.querySelector('.artist-avatar')).borderRadius""")
        note("аватар круглый", "50%" in radius, radius)

    # 5. Плеер: три зоны
    zones = page.evaluate("""() => {
      const p = document.querySelector('.player');
      if (!p) return null;
      const cols = getComputedStyle(p).gridTemplateColumns.split(' ').length;
      return {grid: cols,
              hasTrack: !!p.querySelector('.player-track'),
              hasCenter: !!p.querySelector('.player-center'),
              hasRight: !!p.querySelector('.player-right')};
    }""")
    note("плеер в три зоны", zones and zones["grid"] >= 3 and zones["hasTrack"]
         and zones["hasCenter"] and zones["hasRight"], str(zones))

    # 6. Сердце вместо звезды
    page.locator(".rail-btn[data-view='library']").click()
    page.wait_for_timeout(1200)
    if page.locator("#view .track").count() == 0:
        page.locator(".segment").nth(1).click(); page.wait_for_timeout(1000)
        page.locator("#view .album").first.click(); page.wait_for_timeout(1200)
    hearts = page.locator(".icon-btn.heart")
    note("у треков сердце, а не звезда", hearts.count() >= 1, str(hearts.count()))
    if hearts.count():
        src = hearts.first.locator("img").get_attribute("src")
        note("иконка heart.svg", "heart" in src, src)

    # 7. Навигация рейлом
    page.locator(".rail-btn[data-view='starred']").click(); page.wait_for_timeout(1200)
    note("рейл переключает раздел", "Избранное" in page.inner_text("#view"))
    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(1200)
    note("плейлисты открываются", "Плейлисты" in page.inner_text("#view"))

    page.locator(".rail-btn[data-view='scan']").click(); page.wait_for_timeout(1500)
    note("сканирование открывается", "Сканирование" in page.inner_text("#view"))

    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1500)
    note("возврат в библиотеку", "Библиотека" in page.inner_text("#view"))

    real_bad = [x for x in bad if "getCoverArt" not in x]
    note("нет ошибок загрузки", not real_bad, str(real_bad[:3]))
    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()

print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

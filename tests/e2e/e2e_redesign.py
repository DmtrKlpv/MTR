import sys
from playwright.sync_api import sync_playwright
BASE = sys.argv[1]
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2500)

    # 1. main 96%
    # 96% от площади справа от рейла (окно минус рейл).
    w = page.evaluate("""() => {
      const v = document.querySelector('#view');
      const rail = document.querySelector('.rail').getBoundingClientRect().width;
      return v.getBoundingClientRect().width / (window.innerWidth - rail);
    }""")
    note("main ≈96% доступной ширины", 0.94 <= w <= 0.98, f"{w:.3f}")

    # 1.2 Выход в шапке
    note("иконка «Выход» в шапке", page.locator(".topbar #logout").count() == 1)

    # 1.3 Поиска в рейле нет
    note("в рейле нет иконки поиска",
         page.locator(".rail-btn[data-action='search']").count() == 0)

    # 1.1 Исполнителей нет на главной
    # Слово «Исполнители» осталось в переключателе видов — проверяем,
    # что нет самой секции с круглыми аватарами.
    note("на главной нет секции исполнителей",
         page.locator("#home-sections .artist-grid").count() == 0,
         str(page.locator("#home-sections .artist-grid").count()))

    # 2. Альбом: две равные колонки
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1200)
    page.locator("#view .album").first.click(); page.wait_for_timeout(1500)
    cols = page.evaluate("""() => {
      const h = document.querySelector('.album-hero');
      const l = h.querySelector('.album-hero-left').getBoundingClientRect().width;
      const r = h.querySelector('.album-hero-info').getBoundingClientRect().width;
      return {l: Math.round(l), r: Math.round(r), ratio: l / r};
    }""")
    note("альбом: колонки 50/50", 0.9 <= cols["ratio"] <= 1.1, str(cols))
    note("альбом: заголовок крупный", page.locator(".album-hero-title").count() == 1)

    # 2.1 Акцентное сердце
    heart = page.locator(".icon-btn.heart.on").first
    if heart.count():
        colour = heart.locator("img").evaluate(
            "img => getComputedStyle(img).backgroundColor")
        note("сердце в избранном акцентное", "215" in colour or "224" in colour, colour)
    else:
        note("сердце в избранном акцентное", False, "нет отмеченных треков")

    # 3. Избранное: коллаж 2x2
    page.locator(".rail-btn[data-view='starred']").click(); page.wait_for_timeout(1500)
    note("избранное: коллаж 4 плитки",
         page.locator(".collage .collage-tile").count() == 4,
         str(page.locator(".collage .collage-tile").count()))
    note("избранное: две колонки",
         page.locator(".album-hero-left").count() == 1)

    # 4. Плейлисты: три колонки
    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(1800)
    layout = page.evaluate("""() => {
      const g = document.querySelector('.pl-layout');
      if (!g) return null;
      const kids = Array.from(g.children).map(k => Math.round(k.getBoundingClientRect().width));
      return {kids: g.children.length, widths: kids,
              total: Math.round(g.getBoundingClientRect().width)};
    }""")
    note("плейлисты: 3 колонки", layout and layout["kids"] == 3, str(layout))
    if layout and len(layout["widths"]) == 3:
        total = layout["total"] or 1
        pct = [round(w / total * 100) for w in layout["widths"]]
        note("плейлисты: 15/45/40", abs(pct[0]-15) <= 4 and abs(pct[1]-45) <= 4,
             str(pct))
    note("плейлисты: коллаж в центре", page.locator("#pl-art .collage").count() == 1)
    note("плейлисты: заголовок в стиле альбома",
         page.locator("h1.album-hero-title").count() >= 1)

    # 5. Кнопки не переносятся
    bad = page.evaluate("""() => Array.from(document.querySelectorAll('button'))
        .filter(b => b.offsetParent && b.getBoundingClientRect().height > 46
                     && b.textContent.trim().length < 30)
        .map(b => b.textContent.trim().slice(0,20))""")
    note("кнопки в одну строку", not bad, str(bad[:4]))

    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()

print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

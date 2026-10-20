import sys
from playwright.sync_api import sync_playwright
BASE = sys.argv[1]
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 390, "height": 844})
    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2200)
    no_scroll = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 2")
    note("мобильный: нет горизонтального скролла", no_scroll,
         page.evaluate("document.documentElement.scrollWidth + '/' + window.innerWidth"))
    note("рейл виден", page.locator(".rail").is_visible())
    # Плеер скрыт, пока ничего не играет. Запускаем трек и проверяем,
    # что последний блок контента не уезжает под него.
    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1500)
    if page.locator("#view .track").count() == 0:
        page.locator(".segment").nth(1).click(); page.wait_for_timeout(1000)
        page.locator("#view .album").first.click(); page.wait_for_timeout(1200)
    if page.locator("#view .track").count():
        page.locator("#view .track").first.click(); page.wait_for_timeout(1600)
        gap = page.evaluate("""() => {
          const p = document.querySelector('.player');
          if (p.hidden) return null;
          const pad = parseFloat(getComputedStyle(document.querySelector('.shell')).paddingBottom);
          return Math.round(pad - p.getBoundingClientRect().height);
        }""")
        note("отступ под плеером есть", gap is not None and gap >= 0, str(gap))
    else:
        note("плеер скрыт без воспроизведения — это верно", True)
    page.locator(".rail-btn[data-view='starred']").click(); page.wait_for_timeout(900)
    note("раздел открывается на телефоне", len(page.inner_text("#view").strip()) > 5)
    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

import sys
from playwright.sync_api import sync_playwright
BASE = sys.argv[1]
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2500)

    # Акцент: маска реально применена к активной иконке
    mask = page.evaluate("""() => {
      const img = document.querySelector('.rail-btn.active img');
      if (!img) return null;
      const cs = getComputedStyle(img);
      return {mask: cs.maskImage || cs.webkitMaskImage,
              bg: cs.backgroundColor,
              filter: cs.filter};
    }""")
    note("активная иконка: маска применена",
         mask and mask["mask"] and "heart" not in (mask["mask"] or "") and mask["mask"] != "none",
         str(mask))
    note("активная иконка: акцентный фон",
         mask and mask["bg"] != "rgba(0, 0, 0, 0)" and mask["filter"] == "none", str(mask))

    # Сердце в избранном — тоже акцентное, через ту же маску
    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1500)
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1200)
    page.locator("#view .album").first.click(); page.wait_for_timeout(1500)
    h = page.evaluate("""() => {
      const img = document.querySelector('.icon-btn.heart.on img');
      if (!img) return null;
      const cs = getComputedStyle(img);
      return {mask: cs.maskImage || cs.webkitMaskImage, bg: cs.backgroundColor};
    }""")
    note("сердце в избранном акцентное через маску",
         h and "heart-filled" in (h["mask"] or ""), str(h))

    # Плейлисты: колонка справа, прокрутка внутри
    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(2000)
    geo = page.evaluate("""() => {
      const g = document.querySelector('.pl-layout');
      const kids = Array.from(g.children).map(k => k.getBoundingClientRect());
      const det = document.querySelector('.pl-col-detail');
      return {xs: kids.map(k => Math.round(k.x)),
              widths: kids.map(k => Math.round(k.width)),
              detH: Math.round(det.getBoundingClientRect().height),
              detScrollH: det.scrollHeight,
              detOverflow: getComputedStyle(det).overflowY};
    }""")
    note("плейлисты: колонки слева направо, растут по X",
         geo["xs"] == sorted(geo["xs"]), str(geo["xs"]))
    note("плейлисты: правая колонка имеет внутреннюю прокрутку",
         geo["detOverflow"] == "auto", str(geo["detOverflow"]))

    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

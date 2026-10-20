import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4800"
res = []
def note(n, g, d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1366, "height": 900})
    errs, bad = [], []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 400 else None)

    page.goto(BASE + "/login")
    page.fill("#username", "admin"); page.fill("#password", "adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(1500)

    # 1. Все иконки реально загрузились
    broken = page.evaluate("""() => Array.from(document.querySelectorAll('img.icon'))
        .filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src)""")
    note("все видимые иконки загружены", not broken, str(broken[:3]))

    # 2. Один размер иконок
    sizes = page.evaluate("""() => {
      const set = new Set();
      document.querySelectorAll('img.icon').forEach(i => {
        const r = i.getBoundingClientRect();
        if (r.width) set.add(Math.round(r.width) + 'x' + Math.round(r.height));
      });
      return [...set];
    }""")
    note("иконки одного размера", len(sizes) == 1, f"размеры={sizes}")

    # 3. Ширина main = 90%
    width = page.evaluate("""() => {
      const main = document.querySelector('#view');
      return { main: Math.round(main.getBoundingClientRect().width),
               win: window.innerWidth };
    }""")
    ratio = width["main"] / width["win"]
    note("main занимает ~90% ширины", 0.88 <= ratio <= 0.92, f"{ratio:.3f} ({width})")

    # 4. Никаких эмодзи/глифов в тексте интерфейса
    text = page.inner_text("body")
    glyphs = [c for c in text if c in "▶⏸⏮⏭↻★☆✕＋←⚙⏹"]
    note("в интерфейсе нет символьных глифов", not glyphs, str(glyphs[:5]))

    # 5. Плеер: перемешать и повтор справа
    page.locator("[data-view='library']").click(); page.wait_for_timeout(1000)
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1000)
    page.locator("#view .album", has_text="Opera").first.click(); page.wait_for_timeout(1200)
    page.locator("#view .track").first.click(); page.wait_for_timeout(1500)

    pos = page.evaluate("""() => ({
      shuffle: document.querySelector('#shuffle').getBoundingClientRect().left,
      repeat: document.querySelector('#repeat').getBoundingClientRect().left,
      play: document.querySelector('#play').getBoundingClientRect().left,
      prev: document.querySelector('#prev').getBoundingClientRect().left,
    })""")
    note("«перемешать» и «повтор» правее основных кнопок",
         pos["shuffle"] > pos["play"] and pos["repeat"] > pos["play"], str(pos))

    # 6. Кнопка play меняет иконку
    src_before = page.get_attribute("#play img", "src")
    page.click("#play"); page.wait_for_timeout(900)
    src_after = page.get_attribute("#play img", "src")
    note("иконка play/pause переключается", src_before != src_after, f"{src_before} -> {src_after}")

    # 7. Повтор: иконка меняется off -> all -> one
    # off и all используют одну иконку repeat (all отличается подсветкой),
    # отдельная иконка только у one. Проверяем именно это поведение.
    r1 = page.get_attribute("#repeat img", "src")
    a1 = page.get_attribute("#repeat", "class")
    page.click("#repeat"); page.wait_for_timeout(400)
    r2 = page.get_attribute("#repeat img", "src")
    page.click("#repeat"); page.wait_for_timeout(400)
    r3 = page.get_attribute("#repeat img", "src")
    page.click("#repeat"); page.wait_for_timeout(400)
    r4 = page.get_attribute("#repeat img", "src")
    note("повтор: off/all — repeat, one — repeat-one, затем снова off",
         r1.endswith("repeat.svg") and r2.endswith("repeat.svg")
         and r3.endswith("repeat-one.svg") and r4.endswith("repeat.svg"),
         f"{r1} {r2} {r3} {r4}")

    real_bad = [x for x in bad if "getCoverArt" not in x]
    note("нет ошибок загрузки", not real_bad, str(real_bad[:3]))
    note("нет JS-исключений", not errs, str(errs[:2]))
    b.close()

print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

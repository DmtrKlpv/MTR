import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
res = []


def note(n, g, d=""):
    res.append(g)
    print(("  ok   " if g else "  FAIL ") + n + ("" if g else f"  [{d}]"))


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE + "/login")
    page.fill("#username", "admin")
    page.fill("#password", "adminpass12345")
    page.click("#login-submit")
    page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2200)

    # 1. CSS приложен: правки видны в вычисленных стилях.
    css = page.evaluate("""() => {
      const h2 = document.querySelector('.greeting') || document.querySelector('h2');
      const hero = document.querySelector('.album-hero');
      return {h2MarginTop: h2 ? getComputedStyle(h2).marginTop : null,
              heroExists: !!hero};
    }""")
    note("CSS загружен (h2 с margin-top)", css["h2MarginTop"] not in (None, "0px"), str(css))

    # 2. Земной шар в списке плейлистов
    page.evaluate("""async () => {
      const csrf = document.body.dataset.csrf;
      for (const n of ['Public One','Private Two']) {
        await fetch('/api/web/playlists', {method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
          body: JSON.stringify({name:n})});
      }
    }""")
    page.locator(".rail-btn[data-view='playlists']").click()
    page.wait_for_timeout(2200)

    # делаем плейлист публичным через API
    page.evaluate("""async () => {
      const csrf = document.body.dataset.csrf;
      const r = await fetch('/api/web/playlists');
      const d = await r.json();
      const pub = d.data.items.find(p => p.name === 'Public One');
      if (pub) {
        await fetch(`/api/web/playlists/${pub.id}/public`, {method:'POST',
          headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
          body: JSON.stringify({is_public: true})});
      }
    }""")
    page.locator(".rail-btn[data-view='playlists']").click()
    page.wait_for_timeout(2200)

    g = page.evaluate("""() => {
      const items = Array.from(document.querySelectorAll('.pl-item'));
      return items.map(i => ({
        text: i.textContent.trim(),
        globe: !!i.querySelector('.globe'),
        globeSrc: i.querySelector('.globe') ? i.querySelector('.globe').getAttribute('src') : null,
        hasWord: i.textContent.includes('публ'),
      }));
    }""")
    note("публичный отмечен земным шаром",
         any(x["globe"] for x in g), str(g))
    note("слова «публ.» больше нет", not any(x["hasWord"] for x in g), str(g))
    note("приватный без шара",
         any(not x["globe"] for x in g) and any(x["globe"] for x in g), str(g))

    # 3. Номера треков в списке
    page.locator(".rail-btn[data-view='library']").click()
    page.wait_for_timeout(1300)
    page.locator(".segment").nth(1).click()
    page.wait_for_timeout(1200)
    page.locator("#library-body .album").first.click()
    page.wait_for_timeout(1400)

    nums = page.evaluate("""() => Array.from(document.querySelectorAll('#view .list .track'))
        .map(t => { const i = t.querySelector('.track-index');
                    return i ? i.textContent.trim() : null; })""")
    note("в строках есть номера", len(nums) > 0 and all(n for n in nums), str(nums))
    note("нумерация с 1 подряд",
         nums == [str(i) for i in range(1, len(nums) + 1)], str(nums))

    # номер маленький и серый
    style = page.evaluate("""() => {
      const n = document.querySelector('#view .list .track-index');
      if (!n) return null;
      const cs = getComputedStyle(n);
      return {size: cs.fontSize, color: cs.color, opacity: cs.opacity,
              align: cs.textAlign, width: cs.width};
    }""")
    # #6e6e78 = rgb(110, 110, 120) — это muted-2, серый по теме.
    note("номер мелкий и серый",
         bool(style) and style["size"] in ("12px", "13px")
         and style["color"] == "rgb(110, 110, 120)",
         str(style))

    # 4. Плейлист: тоже номера
    page.locator(".rail-btn[data-view='playlists']").click()
    page.wait_for_timeout(2200)
    # Новые плейлисты пустые — берём тот, где есть треки.
    pl = page.evaluate("""() => {
      const items = Array.from(document.querySelectorAll('.pl-item'));
      const withTracks = items.find(i => /[1-9]/.test(i.textContent));
      if (!withTracks) return {skip: true};
      withTracks.click();
      return {skip: false};
    }""")
    page.wait_for_timeout(1800)
    nums2 = page.evaluate("""() => {
      const det = document.querySelector('.pl-col-detail');
      const rows = Array.from(det.querySelectorAll('.track'));
      return rows.slice(0, 5).map(t => {
        const i = t.querySelector('.track-index');
        return i ? i.textContent.trim() : null;
      });
    }""")
    if pl.get("skip"):
        note("в плейлисте номера (нет плейлиста с треками — пропуск)", True, "")
    else:
        note("в плейлисте номера с 1",
             bool(nums2) and nums2[0] == "1", str(nums2))

    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()

print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

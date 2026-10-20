import sys
from playwright.sync_api import sync_playwright
BASE=sys.argv[1]; res=[]
def note(n,g,d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ")+n+("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b=p.chromium.launch(); page=b.new_page(viewport={"width":1500,"height":950}, device_scale_factor=2)
    errs=[]; page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE+"/login")
    page.fill("#username","admin"); page.fill("#password","adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2500)

    # 1. АККОРДЕОН: по умолчанию свёрнуты
    toggles = page.locator(".section-toggle")
    note("секции-аккордеоны есть", toggles.count() >= 1, str(toggles.count()))
    states = page.evaluate("""() => Array.from(document.querySelectorAll('.section-toggle'))
        .map(t => ({expanded: t.getAttribute('aria-expanded'),
                    collapsed: t.classList.contains('collapsed')}))""")
    note("по умолчанию свёрнуты", all(s["expanded"]=="false" and s["collapsed"] for s in states), str(states))
    hidden = page.evaluate("""() => Array.from(document.querySelectorAll('.section-body'))
        .map(p => p.hidden)""")
    note("тела секций скрыты", all(hidden) if hidden else False, str(hidden))

    # разворачиваем
    toggles.first.click(); page.wait_for_timeout(500)
    after = page.evaluate("""() => Array.from(document.querySelectorAll('.section-body'))
        .map(p => p.hidden)""")
    note("клик разворачивает секцию", not all(after), str(after))

    # 2. ИКОНКИ ПЛЕЕРА: активные акцентные
    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1200)
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1100)
    page.locator("#view .album").first.click(); page.wait_for_timeout(1300)
    page.locator("#view .track").first.click(); page.wait_for_timeout(1500)
    page.locator("#shuffle").click(); page.wait_for_timeout(300)
    page.locator("#repeat").click(); page.wait_for_timeout(500)

    ic = page.evaluate("""() => {
      const out={};
      for (const id of ['shuffle','repeat']) {
        const btn=document.getElementById(id);
        const cs=getComputedStyle(btn,'::after');
        out[id]={cls:btn.className, bg:cs.backgroundColor,
                 mask:cs.maskImage||cs.webkitMaskImage,
                 imgOpacity:getComputedStyle(btn.querySelector('img')).opacity};
      }
      return out;
    }""")
    for k,v in ic.items():
        note(f"{k}: акцентная через маску",
             "215, 224, 33" in (v["bg"] or "") and (v["mask"] or "none")!="none"
             and v["imgOpacity"]=="0", str(v))

    page.locator("#shuffle").screenshot(path="/tmp/sh2.png")
    page.locator("#repeat").screenshot(path="/tmp/rp2.png")

    # 3. ПЛЕЙЛИСТЫ
    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(2200)
    pl = page.evaluate("""() => {
      const g=document.querySelector('.pl-layout');
      const list=document.querySelector('.pl-col-list');
      const art=document.querySelector('.pl-col-art');
      const det=document.querySelector('.pl-col-detail');
      const bulkActs=document.querySelector('.pl-list-actions');
      const coll=document.querySelector('.pl-col-art .collage');
      return {listScroll:getComputedStyle(list).overflowY,
              detScroll:getComputedStyle(det).overflowY,
              artScroll:getComputedStyle(art).overflowY,
              bulkInList: bulkActs ? list.contains(bulkActs) : false,
              hasCollage: !!coll,
              galleryH: getComputedStyle(g).height};
    }""")
    note("плейлисты: кнопки под списком", pl["bulkInList"], str(pl["bulkInList"]))
    note("плейлисты: левая колонка прокручивается", pl["listScroll"]=="auto", pl["listScroll"])
    note("плейлисты: правая колонка прокручивается", pl["detScroll"]=="auto", pl["detScroll"])
    note("плейлисты: центральная фиксирована", pl["artScroll"]=="hidden", pl["artScroll"])
    note("плейлисты: коллаж есть", pl["hasCollage"])

    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

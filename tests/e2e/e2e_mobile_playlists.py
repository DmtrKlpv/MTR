import sys
from playwright.sync_api import sync_playwright
BASE=sys.argv[1]; res=[]
def note(n,g,d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ")+n+("" if g else f"  [{d}]"))
with sync_playwright() as p:
    b=p.chromium.launch(); page=b.new_page(viewport={"width":390,"height":844})
    errs=[]; page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE+"/login")
    page.fill("#username","admin"); page.fill("#password","adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2200)

    m=page.evaluate("""() => ({sw:document.documentElement.scrollWidth, iw:window.innerWidth})""")
    note("главная: нет горизонтального скролла", m["sw"]<=m["iw"]+1, str(m))

    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(2000)
    pl=page.evaluate("""() => {
      const l=document.querySelector('.pl-layout');
      const kids=Array.from(l.children).map(k=>Math.round(k.getBoundingClientRect().width));
      const det=document.querySelector('.pl-col-detail');
      const lst=document.querySelector('.pl-col-list');
      return {cols:getComputedStyle(l).gridTemplateColumns.split(' ').length,
              kids, detY:Math.round(det.getBoundingClientRect().y),
              listY:Math.round(lst.getBoundingClientRect().y),
              sw:document.documentElement.scrollWidth, iw:window.innerWidth};
    }""")
    note("мобильный: одна колонка", pl["cols"]==1, str(pl["cols"]))
    note("мобильный: содержимое плейлиста выше списка", pl["detY"]<pl["listY"], f'{pl["detY"]} vs {pl["listY"]}')
    note("мобильный: нет горизонтального скролла", pl["sw"]<=pl["iw"]+1, f'{pl["sw"]}/{pl["iw"]}')

    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1300)
    if page.locator(".segment").count():
        page.locator(".segment").nth(1).click(); page.wait_for_timeout(1000)
    if page.locator("#library-body .album").count():
        page.locator("#library-body .album").first.click(); page.wait_for_timeout(1300)
        page.locator("#view .list .track").first.click(); page.wait_for_timeout(1500)
        ph=page.evaluate("""() => {
          const h=document.getElementById('now-heart');
          const pr=document.querySelector('.player-right');
          return {hidden:h.hidden, inRight:pr.contains(h),
                  sw:document.documentElement.scrollWidth, iw:window.innerWidth};
        }""")
        note("мобильный: сердце в плеере видно", not ph["hidden"] and ph["inRight"], str(ph))
        note("мобильный: нет скролла с плеером", ph["sw"]<=ph["iw"]+1, f'{ph["sw"]}/{ph["iw"]}')

    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

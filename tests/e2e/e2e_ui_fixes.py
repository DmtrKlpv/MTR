import sys
from playwright.sync_api import sync_playwright
BASE=sys.argv[1]; res=[]
def note(n,g,d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ")+n+("" if g else f"  [{d}]"))

with sync_playwright() as p:
    b=p.chromium.launch(); page=b.new_page(viewport={"width":1500,"height":950})
    errs=[]; page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(BASE+"/login")
    page.fill("#username","admin"); page.fill("#password","adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2200)

    # АЛЬБОМ: две колонки, список не уезжает
    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1400)
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1200)
    page.locator("#view .album").first.click(); page.wait_for_timeout(1500)
    g=page.evaluate("""() => {
      const h=document.querySelector('.album-hero');
      const l=h.querySelector('.album-hero-left').getBoundingClientRect();
      const r=h.querySelector('.album-hero-info').getBoundingClientRect();
      const list=document.querySelector('#view .list').getBoundingClientRect();
      return {leftX:Math.round(l.x),rightX:Math.round(r.x),
              sameRow: Math.abs(l.y-r.y)<=8,
              coverH:Math.round(h.querySelector('.album-hero-cover').getBoundingClientRect().height),
              listY:Math.round(list.y), vh:window.innerHeight};
    }""")
    note("альбом: две колонки в одном ряду", g["rightX"]>g["leftX"] and g["sameRow"], str(g))
    note("альбом: обложка ограничена", g["coverH"]<=430, str(g["coverH"]))
    note("альбом: список треков виден на экране", g["listY"] < g["vh"], str(g))

    # ПЛЕЙЛИСТЫ
    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(2200)
    pl=page.evaluate("""() => {
      const h2=document.querySelector('.pl-page-title');
      const cs=h2?getComputedStyle(h2):null;
      const art=document.querySelector('.pl-col-art .collage');
      const artBox=document.querySelector('.pl-col-art');
      const det=document.querySelector('.pl-col-detail');
      const head=document.querySelector('.pl-page-head');
      const form=head?head.querySelector('.pl-create'):null;
      return {mt: cs?cs.marginTop:null, ml: cs?cs.marginLeft:null,
              artW: art?Math.round(art.getBoundingClientRect().width):null,
              colW: artBox?Math.round(artBox.getBoundingClientRect().width):null,
              detOverflow: det?getComputedStyle(det).overflowY:null,
              formRight: form?Math.round(form.getBoundingClientRect().x):null,
              headRight: head?Math.round(head.getBoundingClientRect().right):null,
              hasCollage: !!art};
    }""")
    note("плейлисты: h2 margin 10/14", pl["mt"]=="10px" and pl["ml"]=="14px", str(pl["mt"])+"/"+str(pl["ml"]))
    note("плейлисты: коллаж есть", pl["hasCollage"])
    note("плейлисты: коллаж на всю ширину колонки",
         pl["artW"] and pl["colW"] and abs(pl["artW"]-pl["colW"])<=2, f"{pl['artW']} vs {pl['colW']}")
    note("плейлисты: нет встроенной прокрутки", pl["detOverflow"]=="visible", str(pl["detOverflow"]))
    note("плейлисты: форма создания справа",
         pl["formRight"] and pl["headRight"] and pl["formRight"]>pl["headRight"]-420, str(pl["formRight"]))

    # ИКОНКИ: активная — акцентный фон, чёрная иконка
    ic=page.evaluate("""() => {
      const btn=document.querySelector('.rail-btn.active');
      const img=btn.querySelector('img');
      return {bg:getComputedStyle(btn).backgroundColor, mask:getComputedStyle(img).maskImage,
              filter:getComputedStyle(img).filter};
    }""")
    note("активная иконка: акцентный фон", "215, 224, 33" in ic["bg"], ic["bg"])
    note("активная иконка: чёрная (без маски)", ic["mask"]=="none" and ic["filter"]=="none", str(ic))

    # СЕРДЦЕ
    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1400)
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1100)
    page.locator("#view .album").first.click(); page.wait_for_timeout(1400)
    # Акцентное сердце рисует псевдоэлемент: сам <img> скрыт, иначе его
    # чёрные пиксели перекрывали бы акцентный фон.
    h=page.evaluate("""() => {
      const btn=document.querySelector('.icon-btn.heart.on');
      if(!btn) return null;
      const cs=getComputedStyle(btn,'::after');
      return {bg:cs.backgroundColor, mask:cs.maskImage||cs.webkitMaskImage,
              imgOpacity:getComputedStyle(btn.querySelector('img')).opacity};
    }""")
    note("сердце: акцентное (псевдоэлемент с маской)",
         h and "215, 224, 33" in h["bg"] and "heart-filled" in (h["mask"] or "")
         and h["imgOpacity"]=="0", str(h))

    # z-index: клик по шестерёнке не перекрыт плеером
    z=page.evaluate("""() => {
      const rail=document.querySelector('.rail');
      const player=document.querySelector('.player');
      return {rail:+getComputedStyle(rail).zIndex, player:+getComputedStyle(player).zIndex};
    }""")
    note("z-index: рейл выше плеера", z["rail"]>z["player"], str(z))

    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

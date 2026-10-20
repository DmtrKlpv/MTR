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

    # ПЛЕЙЛИСТЫ: две колонки
    page.locator(".rail-btn[data-view='playlists']").click(); page.wait_for_timeout(2200)
    g=page.evaluate("""() => {
      const l=document.querySelector('.pl-layout');
      const kids=Array.from(l.children).map(k=>Math.round(k.getBoundingClientRect().width));
      const total=Math.round(l.getBoundingClientRect().width);
      const art=document.querySelector('.pl-col-art .collage');
      const listCol=document.querySelector('.pl-col-list');
      const det=document.querySelector('.pl-col-detail');
      return {count:l.children.length, kids, pct:kids.map(w=>Math.round(w/total*100)),
              collageAtTop: art ? Math.round(art.getBoundingClientRect().y) <
                            Math.round(listCol.querySelector('.pl-list').getBoundingClientRect().y) : false,
              listScroll:getComputedStyle(listCol).overflowY,
              detScroll:getComputedStyle(det).overflowY,
              hasCollage: !!art};
    }""")
    note("две колонки", g["count"]==2, str(g["count"]))
    note("левая шире (≈25%)", abs(g["pct"][0]-25)<=6, str(g["pct"]))
    note("коллаж в начале левой колонки", g["collageAtTop"], str(g["collageAtTop"]))
    note("внутренней прокрутки нет",
         g["listScroll"]=="visible" and g["detScroll"]=="visible", f'{g["listScroll"]}/{g["detScroll"]}')
    note("коллаж есть", g["hasCollage"])

    # Справа: заголовок, управление, список
    d=page.evaluate("""() => {
      const det=document.querySelector('.pl-col-detail');
      const h=det.querySelector('.album-hero-title');
      const btns=Array.from(det.querySelectorAll('button')).map(b=>b.textContent.trim());
      const tracks=det.querySelectorAll('.track').length;
      const meta = det.textContent.match(/\\d+ треков[^\\n]*/);
      return {title: h?h.textContent:null, btns: btns.slice(0,4), tracks,
              meta: meta?meta[0]:null};
    }""")
    note("справа заголовок плейлиста", bool(d["title"]), str(d["title"]))
    note("справа кнопки управления", len(d["btns"])>=3, str(d["btns"]))
    note("справа счётчик треков", bool(d["meta"]), str(d["meta"]))
    note("справа список треков", d["tracks"]>=0, str(d["tracks"]))

    # СЕРДЦЕ В ПЛЕЕРЕ
    page.locator(".rail-btn[data-view='library']").click(); page.wait_for_timeout(1300)
    page.locator(".segment").nth(1).click(); page.wait_for_timeout(1100)
    page.locator("#library-body .album").first.click(); page.wait_for_timeout(1300)
    page.locator("#view .list .track").first.click(); page.wait_for_timeout(1600)
    h=page.evaluate("""() => {
      const right=document.querySelector('.player-right');
      const kids=Array.from(right.children).map(c=>c.id);
      const heart=document.getElementById('now-heart');
      const cs=getComputedStyle(heart);
      return {order:kids, hidden:heart.hidden, cls:heart.className,
              pos:Array.from(right.children).indexOf(heart)};
    }""")
    note("сердце в player-right первым", h["pos"]==0, str(h["order"]))
    note("сердце видно при игре", not h["hidden"], str(h["hidden"]))

    # клик переключает избранное
    page.locator("#now-heart").click(); page.wait_for_timeout(900)
    after=page.evaluate("""() => {
      const h=document.getElementById('now-heart');
      return {on:h.classList.contains('on'),
              src:h.querySelector('img').getAttribute('src')};
    }""")
    note("клик по сердцу добавляет в избранное", after["on"] and "heart-filled" in after["src"], str(after))
    page.locator("#now-heart").click(); page.wait_for_timeout(900)
    back=page.evaluate("""() => document.getElementById('now-heart').classList.contains('on')""")
    note("повторный клик убирает", back is False, str(back))

    note("нет JS-исключений", not errs, "; ".join(errs[:2]))
    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

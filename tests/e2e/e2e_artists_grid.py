import sys
from playwright.sync_api import sync_playwright
res=[]
def note(n,g,d=""):
    res.append(g); print(("  ok   " if g else "  FAIL ")+n+("" if g else f"  [{d}]"))
with sync_playwright() as p:
    b=p.chromium.launch(); page=b.new_page(viewport={"width":1500,"height":950})
    page.goto(sys.argv[1]+"/login")
    page.fill("#username","admin"); page.fill("#password","adminpass12345")
    page.click("#login-submit"); page.wait_for_url("**/app", timeout=15000)
    page.wait_for_timeout(2000)
    page.locator(".segment").nth(0).click(); page.wait_for_timeout(1500)
    grid = page.evaluate("""() => {
      const g = document.querySelector('#library-body .artist-grid');
      if (!g) return null;
      const cs = getComputedStyle(g);
      return {display: cs.display, overflow: cs.overflowX,
              radius: getComputedStyle(g.querySelector('.artist-avatar')).borderRadius,
              cols: cs.gridTemplateColumns.split(' ').length};
    }""")
    note("исполнители: сетка (не слайдер)",
         grid and grid["display"]=="grid" and grid["overflow"]!="auto", str(grid))
    note("исполнители: несколько колонок", grid and grid["cols"]>=2, str(grid))
    note("аватары круглые", grid and "50%" in grid["radius"], str(grid))
    b.close()
print(f"\nИТОГ: {sum(res)}/{len(res)}")
sys.exit(0 if all(res) else 1)

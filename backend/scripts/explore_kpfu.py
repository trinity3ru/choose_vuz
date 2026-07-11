"""Разведка сайта КФУ — временный скрипт."""
import asyncio
import re
import json
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")

URL = "https://kpfu.ru/computing-technology/abiturientam/application"


async def main():
    captured = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        async def on_response(response):
            url = response.url
            if any(k in url.lower() for k in ("api", "ajax", "rating", "list", "abit", "sspvo", "priem")):
                try:
                    ct = response.headers.get("content-type", "")
                    body = await response.text()
                    captured.append({"url": url, "status": response.status, "ct": ct, "len": len(body), "body": body[:3000]})
                except Exception:
                    pass

        page.on("response", on_response)
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(5000)
        print("TITLE:", await page.title())
        iframes = page.locator("iframe")
        print("IFRAMES:", await iframes.count())
        for i in range(await iframes.count()):
            src = await iframes.nth(i).get_attribute("src")
            print(" IFRAME:", src)
        selects = await page.locator("select").count()
        print("SELECTS:", selects)
        for i in range(selects):
            sel = page.locator("select").nth(i)
            name = await sel.get_attribute("name") or await sel.get_attribute("id") or f"select_{i}"
            opts = await sel.locator("option").all_text_contents()
            print(f"--- SELECT {name} ({len(opts)} options) ---")
            for o in opts[:20]:
                print(" ", o.strip()[:150])
            if len(opts) > 20:
                print("  ...")

        # Ищем Vue/React контейнеры и скрипты
        for sel in ["#app", "[data-v-app]", ".application", "form", "table"]:
            cnt = await page.locator(sel).count()
            if cnt:
                print(f"LOCATOR {sel}: {cnt}")
        html = await page.content()
        with open("scripts/kpfu_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved HTML to scripts/kpfu_page.html, len=", len(html))
        for pat in [r"https?://[^\"'\s]+", r"/api/[^\"'\s]+"]:
            for m in re.finditer(pat, html):
                s = m.group(0)
                if any(k in s.lower() for k in ("api", "ajax", "rating", "list", "abit")):
                    print("HTML URL:", s[:200])

        print("\n=== CAPTURED RESPONSES ===")
        for c in captured:
            print(json.dumps({k: v for k, v in c.items() if k != "body"}, ensure_ascii=False))
            if "json" in c["ct"]:
                print(c["body"][:1500])
            else:
                print(c["body"][:500])
            print("---")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

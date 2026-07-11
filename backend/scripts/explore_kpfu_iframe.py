"""Разведка iframe КФУ abiturient.kpfu.ru."""
import asyncio
import json
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")

URL = "https://abiturient.kpfu.ru/entrant/abit_entrant_originals_list?p_faculty=9&p_typeofstudy=1"


async def main():
    captured = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()

        async def on_response(response):
            url = response.url
            if "abiturient.kpfu.ru" in url and response.request.resource_type in ("xhr", "fetch", "document"):
                try:
                    ct = response.headers.get("content-type", "")
                    body = await response.text()
                    if len(body) > 50:
                        captured.append({
                            "url": url,
                            "method": response.request.method,
                            "post": response.request.post_data,
                            "status": response.status,
                            "ct": ct,
                            "len": len(body),
                            "body": body[:5000],
                        })
                except Exception:
                    pass

        page.on("response", on_response)
        await page.goto(URL, wait_until="networkidle", timeout=90000)
        await page.wait_for_timeout(3000)

        print("TITLE:", await page.title())
        selects = await page.locator("select").count()
        print("SELECTS:", selects)
        for i in range(selects):
            sel = page.locator("select").nth(i)
            name = await sel.get_attribute("name") or await sel.get_attribute("id") or f"select_{i}"
            opts = await sel.locator("option").all_text_contents()
            print(f"--- SELECT {name} ({len(opts)} options) ---")
            for o in opts[:30]:
                print(" ", o.strip()[:180])
            if len(opts) > 30:
                print("  ...")

        # choices.js custom selects
        choices = await page.locator(".choices").count()
        print("CHOICES widgets:", choices)

        html = await page.content()
        with open("scripts/kpfu_iframe.html", "w", encoding="utf-8") as f:
            f.write(html)

        print("\n=== CAPTURED ===")
        for c in captured:
            print(json.dumps({k: v for k, v in c.items() if k != "body"}, ensure_ascii=False))
            print(c["body"][:2000])
            print("---")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

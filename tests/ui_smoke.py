"""Click through the whole UI and report page errors / error toasts. Needs: playwright + Chrome,
the engine running, and `npx vite preview` serving the built UI on :4173.
Usage: python tests/ui_smoke.py <engine-port>"""
import asyncio
import sys

from playwright.async_api import async_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome")
        pg = await b.new_page(viewport={"width": 1480, "height": 920})
        errors = []
        pg.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        await pg.goto(f"http://localhost:4173/?port={PORT}")
        await pg.wait_for_selector(".hero", timeout=30000)

        async def toasts(where):
            for t in await pg.query_selector_all(".toast.error"):
                errors.append(f"{where}: toast '{await t.inner_text()}'")

        await pg.click(".proj-card")
        await pg.wait_for_selector(".clip-card", timeout=30000)
        n = len(await pg.query_selector_all(".clip-card"))
        for i in range(n):
            await pg.click(f".clip-card >> nth={i}")
            await pg.wait_for_timeout(400)
            for tab in ("Captions", "Effects", "Voice", "Layout", "Export"):
                await pg.click(f"button.vt:has-text('{tab}')")
                await pg.wait_for_timeout(350)
                await toasts(f"clip {i} tab {tab}")
            await pg.click("button.vt:has-text('Captions')")
            for sc in await pg.query_selector_all(".style-card"):
                await sc.click()
                await pg.wait_for_timeout(150)
            await pg.click("button.vt:has-text('Layout')")
            for mode in ("Crop", "Facecam", "Fit", "Blur"):
                await pg.click(f".segmented button:has-text('{mode}')")
                await pg.wait_for_timeout(300)
            await pg.click("button.vt:has-text('Effects')")
            await pg.click(".fx-add-btn:has-text('Text pop')")
            await pg.wait_for_timeout(500)
            await pg.click("button[title='Zoom in']")
            await pg.click("button[title='Zoom out']")
            await pg.click("button[title='Back to this clip']")
            await toasts(f"clip {i} actions")
        await pg.click(".nav-btn >> nth=1")
        await pg.wait_for_timeout(800)
        await pg.click(".nav-btn >> nth=2")
        await pg.wait_for_timeout(800)
        await toasts("pages")
        print("\n".join(errors) if errors else "UI OK: no errors")
        await b.close()
        sys.exit(1 if errors else 0)

asyncio.run(main())

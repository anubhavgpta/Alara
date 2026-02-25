"""
alara/integrations/browser.py

Controls Chrome/Edge via Chrome DevTools Protocol (CDP) using Playwright.
Week 1-2: Stubs. Week 7-8: Real Playwright implementation.
"""
from loguru import logger


class BrowserIntegration:

    def new_tab(self, params: dict):
        logger.info("[STUB] Opening new browser tab")
        # TODO Week 7:
        # from playwright.sync_api import sync_playwright
        # Connect to running Chrome via CDP: playwright.chromium.connect_over_cdp("http://localhost:9222")
        # browser.new_page()

    def navigate(self, params: dict):
        url = params.get("url", "")
        if not url.startswith("http"):
            url = f"https://{url}"
        logger.info(f"[STUB] Navigating to: {url}")

    def search(self, params: dict):
        query = params.get("query", "")
        logger.info(f"[STUB] Searching browser for: {query}")
        # Will navigate to: https://www.google.com/search?q={query}

    def close_tab(self, params: dict):
        logger.info("[STUB] Closing current browser tab")

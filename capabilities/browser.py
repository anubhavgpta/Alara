"""Browser automation capability using Playwright sync API."""

import os
import re
import urllib.parse
from typing import Any, Dict

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from alara.capabilities.base import BaseCapability, CapabilityResult


class BrowserCapability(BaseCapability):
    """Browser automation capability using Playwright."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.headless = config.get("browser_headless", True)

    def execute(self, operation: str, params: Dict[str, Any]) -> CapabilityResult:
        """Execute browser operation using Playwright sync API."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; "
                    "Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()
            page.set_default_timeout(10000)
            try:
                result = self._dispatch(page, operation, params)
                return CapabilityResult(success=True, output=result)
            except Exception as e:
                return CapabilityResult(success=False, error=str(e))
            finally:
                browser.close()

    def _dispatch(self, page, operation: str, params: Dict[str, Any]) -> str:
        """Dispatch operation to appropriate handler."""
        if operation == "navigate":
            return self._navigate(page, params)
        elif operation == "scrape":
            return self._scrape(page, params)
        elif operation == "screenshot":
            return self._screenshot(page, params)
        elif operation == "click":
            return self._click(page, params)
        elif operation == "type":
            return self._type(page, params)
        elif operation == "fill_form":
            return self._fill_form(page, params)
        elif operation == "submit_form":
            return self._submit_form(page, params)
        elif operation == "get_links":
            return self._get_links(page, params)
        elif operation == "extract_table":
            return self._extract_table(page, params)
        elif operation == "wait_for":
            return self._wait_for(page, params)
        elif operation == "search_web":
            return self._search_web(page, params)
        else:
            raise ValueError(f"Unsupported operation: {operation}")

    def _navigate(self, page, params: Dict[str, Any]) -> str:
        """Navigate to URL."""
        url = params["url"]
        page.goto(url)
        title = page.title()
        return f"Navigated to {url} — Title: {title}"

    def _scrape(self, page, params: Dict[str, Any]) -> str:
        """Scrape page content."""
        url = params["url"]
        selector = params.get("selector")
        
        page.goto(url)
        
        if selector:
            text = page.locator(selector).inner_text()
        else:
            text = page.inner_text("body")
        
        # Strip excessive whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Limit to 5000 characters
        if len(text) > 5000:
            text = text[:5000] + "..."
        
        return text

    def _screenshot(self, page, params: Dict[str, Any]) -> str:
        """Take screenshot of page."""
        url = params["url"]
        path = params["path"]
        
        # Resolve path using same pattern as FilesystemCapability
        resolved_path = self._resolve_path(path)
        
        page.goto(url)
        page.screenshot(path=resolved_path, full_page=True)
        return f"Screenshot saved to {path}"

    def _click(self, page, params: Dict[str, Any]) -> str:
        """Click element on page."""
        url = params.get("url")
        selector = params["selector"]
        
        if url:
            page.goto(url)
        
        page.locator(selector).click()
        return f"Clicked {selector}"

    def _type(self, page, params: Dict[str, Any]) -> str:
        """Type text into element."""
        selector = params["selector"]
        text = params["text"]
        
        page.locator(selector).fill(text)
        return f"Typed into {selector}"

    def _fill_form(self, page, params: Dict[str, Any]) -> str:
        """Fill form fields."""
        url = params["url"]
        fields = params["fields"]  # dict selector -> value
        
        page.goto(url)
        
        for selector, value in fields.items():
            page.locator(selector).fill(value)
        
        return "Form filled"

    def _submit_form(self, page, params: Dict[str, Any]) -> str:
        """Fill and submit form."""
        url = params["url"]
        fields = params["fields"]
        submit_selector = params["submit_selector"]
        
        page.goto(url)
        
        for selector, value in fields.items():
            page.locator(selector).fill(value)
        
        page.locator(submit_selector).click()
        return "Form submitted"

    def _get_links(self, page, params: Dict[str, Any]) -> str:
        """Get links from page."""
        url = params["url"]
        filter_text = params.get("filter")
        
        page.goto(url)
        
        links = page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({text: e.innerText, href: e.href}))"
        )
        
        # Apply filter if provided
        if filter_text:
            links = [link for link in links if filter_text in link["href"]]
        
        # Limit to 20 links
        links = links[:20]
        
        # Format as string
        formatted_links = []
        for i, link in enumerate(links, 1):
            formatted_links.append(f"{i}. {link['text']}\n   {link['href']}")
        
        return "\n\n".join(formatted_links)

    def _extract_table(self, page, params: Dict[str, Any]) -> str:
        """Extract table data."""
        url = params["url"]
        selector = params.get("selector", "table")
        
        page.goto(url)
        
        # Extract table data
        table_data = page.eval_on_selector(
            selector,
            """table => {
                const rows = Array.from(table.querySelectorAll('tr'));
                return rows.map(row => {
                    const cells = Array.from(row.querySelectorAll('td, th'));
                    return cells.map(cell => cell.innerText.trim());
                });
            }"""
        )
        
        # Format as string
        formatted_rows = []
        for row in table_data:
            formatted_rows.append(" | ".join(row))
        
        return "\n".join(formatted_rows)

    def _wait_for(self, page, params: Dict[str, Any]) -> str:
        """Wait for element to appear."""
        url = params["url"]
        selector = params["selector"]
        timeout_ms = params.get("timeout_ms", 5000)
        
        page.goto(url)
        page.wait_for_selector(selector, timeout=timeout_ms)
        return f"Element {selector} found"

    def _search_web(self, page, params: Dict[str, Any]) -> str:
        """Search the web."""
        query = params["query"]
        engine = params.get("engine", "google")
        
        if engine == "google":
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        else:
            # Default to Google
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        
        page.goto(url)
        
        # Extract search results
        titles = page.eval_on_selector_all(
            "h3",
            "els => els.map(e => e.innerText)"
        )
        
        urls = page.eval_on_selector_all(
            "cite",
            "els => els.map(e => e.innerText)"
        )
        
        # Combine and format top 5 results
        results = []
        for i in range(min(5, len(titles), len(urls))):
            results.append(f"{i+1}. {titles[i]}\n   {urls[i]}")
        
        return "\n\n".join(results)

    def _resolve_path(self, path: str) -> str:
        """Resolve path using same pattern as FilesystemCapability."""
        if path is None or path.strip() == "":
            return str(os.getcwd())

        # Substitute environment variables
        path_string = str(path)
        path_string = path_string.replace("$env:USERPROFILE", str(os.path.expanduser("~")))
        path_string = path_string.replace("%USERPROFILE%", str(os.path.expanduser("~")))
        path_string = path_string.replace("$env:HOME", str(os.path.expanduser("~")))
        path_string = path_string.replace("$HOME", str(os.path.expanduser("~")))
        
        # Handle ~ expansion
        if path_string.startswith("~") or path_string.startswith("~/"):
            if path_string.startswith("~"):
                path_string = str(os.path.expanduser("~")) + path_string[1:]
            else:
                path_string = str(os.path.expanduser("~")) + path_string[2:]

        # Expand using pathlib
        result = os.path.expanduser(path_string)

        # Anchor relative paths to home directory
        if os.path.isabs(result):
            return result
        else:
            return os.path.join(os.path.expanduser("~"), result)

    def supports(self, operation: str) -> bool:
        """Return whether this capability handles the operation."""
        supported_ops = {
            "navigate", "scrape", "screenshot", "click", "type",
            "fill_form", "submit_form", "get_links", "extract_table",
            "wait_for", "search_web"
        }
        return operation in supported_ops

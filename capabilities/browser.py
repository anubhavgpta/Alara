"""Browser automation capability using Playwright sync API."""

import os
import random
import re
import time
import urllib.parse
from typing import Any, Dict

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from capabilities.base import BaseCapability, CapabilityResult


# Minimum character count for search results to be considered useful
MIN_RESULT_LENGTH = 200


class BrowserCapability(BaseCapability):
    """Browser automation capability using Playwright."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # DuckDuckGo blocks headless browsers — always use headed mode for web search
        self.headless = False

    def execute(self, operation: str, params: Dict[str, Any]) -> CapabilityResult:
        """Execute browser operation using Playwright sync API."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US"
            )
            page = context.new_page()
            page.set_default_timeout(10000)
            
            # Add extra headers to look more like a real browser
            page.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            })
            
            try:
                result = self._dispatch(page, browser, operation, params)
                return CapabilityResult(success=True, output=result)
            except Exception as e:
                return CapabilityResult(success=False, error=str(e))
            finally:
                browser.close()

    def _extract_real_url(self, ddg_url: str) -> str:
        """Extract real URL from DuckDuckGo redirect."""
        if 'duckduckgo.com/l/' in ddg_url:
            try:
                parsed = urllib.parse.urlparse(ddg_url)
                params = urllib.parse.parse_qs(parsed.query)
                if 'uddg' in params:
                    return urllib.parse.unquote(params['uddg'][0])
            except Exception:
                pass
        return ddg_url

    def _dispatch(self, page, browser, operation: str, params: Dict[str, Any]) -> str:
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
            return self._search_web(page, browser, params)
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

        # Wait for body
        try:
            page.wait_for_selector(
                "body", timeout=8000
            )
        except Exception:
            pass

        if selector:
            try:
                text = page.locator(
                    selector
                ).inner_text()
            except Exception:
                text = page.inner_text("body")
        else:
            # Remove noise elements before scraping
            page.evaluate("""() => {
                const selectors = [
                    'nav', 'footer', 'header',
                    'script', 'style', 'noscript',
                    '.nav', '.footer', '.header',
                    '.sidebar', '.advertisement',
                    '.cookie', '.popup', '.modal'
                ];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel)
                        .forEach(el => el.remove());
                });
            }""")
            text = page.inner_text("body")

        # Strip excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        text = text.strip()

        # Limit to 8000 characters
        if len(text) > 8000:
            text = text[:8000] + "..."

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

    def _do_search(self, page, query: str) -> str:
        """Core search implementation that can be called for retry."""
        url = (
            "https://html.duckduckgo.com/html/"
            f"?q={urllib.parse.quote(query)}"
        )

        page.goto(url)

        # Wait a bit for the page to fully load
        import time
        time.sleep(2)

        # Wait for results to load
        try:
            page.wait_for_selector(
                ".result", timeout=10000
            )
        except Exception:
            # Try alternative selector
            try:
                page.wait_for_selector(
                    "div[class*='result']", timeout=5000
                )
            except Exception:
                # Wait a bit more and try again
                time.sleep(3)
                pass

        # Extract results with multiple selector attempts
        raw_results = page.eval_on_selector_all(
            ".result, div[class*='result'], article",
            """els => els.slice(0, 15).map(el => {
                // Try multiple selectors for title
                const titleEl = el.querySelector('.result__title') || 
                                el.querySelector('h2') || 
                                el.querySelector('h3') || 
                                el.querySelector('a') ||
                                el.querySelector('[class*="title"]');
                
                // Try multiple selectors for content in priority order
                const snippetEl = el.querySelector('.result__snippet') ||
                                 el.querySelector('.result__body') ||
                                 el.querySelector('[class*="body"]') ||
                                 el.querySelector('p');
                
                // Try multiple selectors for URL
                const urlEl = el.querySelector('.result__url') ||
                             el.querySelector('a') ||
                             el.querySelector('[href]');
                
                const title = titleEl ? (titleEl.innerText || titleEl.textContent || '').trim() : '';
                
                // Extract content with fallbacks
                let content = '';
                if (snippetEl) {
                    content = snippetEl.innerText || snippetEl.textContent || '';
                }
                
                // If no snippet, try to get any text content from the result
                if (!content) {
                    const allText = el.innerText || el.textContent || '';
                    // Remove title from the text to get just the content
                    if (allText && title) {
                        content = allText.replace(title, '').trim();
                    } else if (allText) {
                        content = allText.trim();
                    }
                }
                
                // Limit content to 300 chars
                content = content.substring(0, 300);
                
                let url = urlEl ? (urlEl.href || urlEl.innerText || urlEl.textContent || '').trim() : '';
                
                return {
                    title: title,
                    url: url,
                    snippet: content
                };
            }).filter(r => r.title && 
                        r.title.length > 0 && 
                        !r.title.toLowerCase().includes('advertisement') && 
                        !r.title.toLowerCase().includes('sponsored') &&
                        !r.url.includes('duckduckgo.com/y.js'))
        """)

        if not raw_results:
            # Fallback: try to get any text content
            try:
                page_content = page.inner_text("body")
                if page_content and len(page_content) > 100:
                    return f"Search results page loaded. Content preview:\n{page_content[:500]}..."
            except Exception:
                pass
            return f"No results found for: {query}"

        # Deduplicate results by URL and clean DuckDuckGo redirects
        seen_urls = set()
        unique_results = []
        
        for r in raw_results:
            url = r.get("url", "")
            title = r.get("title", "").lower()
            
            # Skip ads and sponsored content more aggressively
            if any(ad_word in title for ad_word in [
                'advertisement', 'sponsored', 'ad', 'promotion',
                'best data science', 'program', 'course', 'learning'
            ]) or 'duckduckgo.com/y.js' in url:
                continue
                
            if not url:
                continue
                
            # Extract real URL from DuckDuckGo redirect
            real_url = self._extract_real_url(url)
            
            # Normalize URL for deduplication (remove tracking params)
            base_url = real_url.split('&')[0] if '&' in real_url else real_url
            
            if base_url not in seen_urls:
                seen_urls.add(base_url)
                # Update the result with the cleaned URL
                r["url"] = real_url
                unique_results.append(r)
        
        # Limit to top 10 unique organic results
        results = unique_results[:10]

        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "").strip()
            url = r.get("url", "").strip()
            snippet = r.get("snippet", "").strip()
            
            # Skip results where both title and snippet are empty
            if not title and not snippet:
                continue
                
            formatted.append(
                f"{i}. {title}\n"
                f"   {url}\n"
                f"   {snippet}"
            )

        return "\n\n".join(formatted) if formatted \
            else f"No results found for: {query}"

    def _search_web(self, page, browser, params: Dict[str, Any]) -> str:
        """Search the web using DuckDuckGo with retry for thin results."""
        query = params["query"]
        
        # Polite delay between searches
        delay = random.uniform(1.0, 2.5)
        time.sleep(delay)
        
        # First attempt
        output = self._do_search(page, query)
        
        # Check if results are too thin and retry if needed
        if len(output) < MIN_RESULT_LENGTH:
            # Rephrase query and retry once
            retry_query = query + " overview"
            from loguru import logger
            logger.warning(
                f"[browser] Search returned thin "
                f"results ({len(output)} chars), "
                f"retrying with fresh context: "
                f"'{retry_query}'"
            )
            # Longer delay before retry
            time.sleep(random.uniform(3.0, 5.0))
            
            # Fresh context for retry
            retry_context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US"
            )
            retry_page = retry_context.new_page()
            retry_page.set_default_timeout(10000)
            
            # Add extra headers to look more like a real browser
            retry_page.set_extra_http_headers({
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            })
            
            try:
                output = self._do_search(retry_page, retry_query)
            finally:
                retry_context.close()
        
        # Return whatever we have (even if still thin)
        return output

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

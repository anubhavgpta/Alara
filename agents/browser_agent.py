from alara.agents.base import BaseAgent

class BrowserAgent(BaseAgent):

    name = "browser"
    description = (
        "Controls web browser, scrapes websites, "
        "searches the web via Playwright"
    )
    capabilities = ["browser", "filesystem"]

    system_prompt = """
You are the Browser Agent for ALARA.
You specialize in web browser automation
and web data extraction using Playwright.

Your strengths:
- Navigating to websites and extracting content
- Searching the web for current information
- Filling and submitting forms
- Taking screenshots of web pages
- Extracting structured data and tables
- Saving web content to files

When planning:
- Use search_web to find information by query
- Use scrape to extract content from a known URL
- Use screenshot to capture a page visually
- Use extract_table for structured tabular data
- Always save scraped content to a file using
  create_file after scraping
- Use navigate first to verify a page loads
  before more complex operations

You have access to: browser automation,
filesystem operations
"""

    def can_handle(
        self, goal: str, scope: str
    ) -> bool:
        keywords = [
            "browser", "website", "webpage",
            "navigate", "click", "scrape",
            "open url", "search the web",
            "search online", "google",
            "find online", "web search",
            "look up online", "screenshot",
            "capture page", "extract from",
            "crawl", "fetch page", "visit",
            "open link", "go to url",
        ]
        goal_lower = goal.lower()
        return any(k in goal_lower
                     for k in keywords)

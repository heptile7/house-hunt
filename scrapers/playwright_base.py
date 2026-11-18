import logging

from scrapers.base_scraper import SCRAPER_API_KEY, BaseScraper

logger = logging.getLogger(__name__)

_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
]

_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] });
"""


class PlaywrightScraper(BaseScraper):
    """
    Drop-in replacement for BaseScraper that fetches pages using headless Chromium.
    Runs fully in the background — no window, no user interaction.
    Each call to scrape() launches one browser, reuses it across pages, then closes it.
    """

    def _start_browser(self, use_proxy: bool = False):
        """
        Launch headless Chromium.
        use_proxy=True: route through ScraperAPI residential proxy (bypasses WAF/CDN IP blocks).
        Requires SCRAPER_API_KEY in .env.
        """
        from playwright.sync_api import sync_playwright

        self._pw_mgr = sync_playwright()
        self._pw = self._pw_mgr.__enter__()
        self._browser = self._pw.chromium.launch(headless=True, args=_BROWSER_ARGS)

        proxy = None
        if use_proxy and SCRAPER_API_KEY:
            proxy = {
                "server": "http://proxy.scraperapi.com:8001",
                "username": "scraperapi",
                "password": SCRAPER_API_KEY,
            }
            logger.debug("[Playwright] Using ScraperAPI residential proxy")

        self._context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            extra_http_headers={
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            proxy=proxy,
            ignore_https_errors=bool(proxy),  # proxy is MITM, cert won't match
        )
        self._context.add_init_script(_INIT_SCRIPT)
        logger.debug("[Playwright] Browser started")

    def _stop_browser(self):
        try:
            if getattr(self, "_context", None):
                self._context.close()
            if getattr(self, "_browser", None):
                self._browser.close()
            if getattr(self, "_pw_mgr", None):
                self._pw_mgr.__exit__(None, None, None)
        except Exception as e:
            logger.debug(f"[Playwright] cleanup error: {e}")
        self._context = self._browser = self._pw = self._pw_mgr = None
        logger.debug("[Playwright] Browser stopped")

    def _fetch_page(self, url: str, wait_selector: str = None) -> str:
        """
        Navigate to url with a real Chromium instance and return the page HTML.
        wait_selector: optional CSS selector to wait for before returning.
        """
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=6_000)
                except Exception:
                    pass
            # Short wait for JS-injected data (e.g. __NEXT_DATA__, __INITIAL_STATE__)
            page.wait_for_timeout(2_000)
            return page.content()
        except Exception as e:
            logger.debug(f"[Playwright] fetch error {url}: {e}")
            raise
        finally:
            page.close()

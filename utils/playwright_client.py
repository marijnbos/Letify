"""
Playwright-based HTTP client (CloakBrowser-like implementation)
for evading website anti-bot detection using browser automation.
"""

import asyncio
import random
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
import re

from playwright.async_api import async_playwright, Page, BrowserContext, Browser
import inspect

try:
    import cloakbrowser
    _cloakbrowser = cloakbrowser
except Exception:
    _cloakbrowser = None

from config import HTTP_TIMEOUT, USE_PROXIES, PROXY_LIST
from utils.logging_config import configure_logging

logger = configure_logging(
    name="realestate_scraper.playwright_client", 
    log_file="logs/scraper.log"
)


class PlaywrightHttpClient:
    """HTTP client using Playwright with stealth plugins to avoid detection"""
    
    # Browser profiles with realistic viewport sizes and device info
    BROWSER_PROFILES = [
        {
            "name": "Chrome Windows",
            "viewport": {"width": 1920, "height": 1080},
            "device_scale_factor": 1,
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
        {
            "name": "Chrome macOS",
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 2,
            "locale": "en-US",
            "timezone_id": "America/Los_Angeles",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
        {
            "name": "Firefox Windows",
            "viewport": {"width": 1366, "height": 768},
            "device_scale_factor": 1,
            "locale": "en-US",
            "timezone_id": "Europe/London",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        },
        {
            "name": "Chrome Linux",
            "viewport": {"width": 1920, "height": 1080},
            "device_scale_factor": 1,
            "locale": "en-US",
            "timezone_id": "Europe/Amsterdam",
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        },
        {
            "name": "Safari macOS",
            "viewport": {"width": 1440, "height": 900},
            "device_scale_factor": 2,
            "locale": "en-US",
            "timezone_id": "Europe/Paris",
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        },
    ]
    
    # Anti-bot patterns to detect
    ANTI_BOT_PATTERNS = [
        "Je bent bijna op de pagina die je zoekt",
        "We houden ons platform graag veilig en spamvrij",
        "captcha",
        "Cloudflare",
        "DDoS protection",
        "Ik ben geen robot",
        "Just a moment",
        "checking your browser",
        "security check",
        "challenge",
        "human verification",
    ]
    
    def __init__(self,
                 timeout: float = HTTP_TIMEOUT,
                 max_retries: int = 3,
                 retry_min_wait: int = 1,
                 retry_max_wait: int = 10,
                 semaphore: Optional[asyncio.Semaphore] = None,
                 use_proxies: bool = USE_PROXIES,
                 proxy_list: Optional[List[str]] = None,
                 headless: bool = True):
        """
        Initialize Playwright HTTP client with stealth
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_min_wait: Minimum wait time between retries
            retry_max_wait: Maximum wait time between retries
            semaphore: Optional semaphore for limiting concurrent requests
            use_proxies: Whether to use proxies
            proxy_list: List of proxy URLs
            headless: Whether to run browser in headless mode
        """
        self.timeout = int(timeout * 1000)  # Convert to milliseconds
        self.max_retries = max_retries
        self.retry_min_wait = retry_min_wait
        self.retry_max_wait = retry_max_wait
        self.semaphore = semaphore or asyncio.Semaphore(10)
        self.use_proxies = use_proxies
        self.proxy_list = proxy_list if proxy_list is not None else PROXY_LIST
        self.headless = headless
        
        self.browser: Optional[Browser] = None
        self.playwright = None
        self._lock = asyncio.Lock()
        
        if self.use_proxies and not self.proxy_list:
            logger.warning("Proxy usage enabled but no proxies provided. Disabling proxy usage.")
            self.use_proxies = False
    
    async def _initialize_browser(self):
        """Initialize Playwright browser with stealth mode"""
        if self.browser is not None:
            return
        
        async with self._lock:
            if self.browser is not None:
                return
            # Prefer cloakbrowser when available (always enabled if installed)
            launch_args = {
                "headless": self.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                    "--disable-component-update",
                    "--disable-default-apps",
                ]
            }

            proxy_url = None
            if self.use_proxies and self.proxy_list:
                proxy_url = random.choice(self.proxy_list)
                parsed = urlparse(proxy_url)
                # cloakbrowser may accept proxy settings differently; pass raw URL and credentials
                launch_args["proxy"] = proxy_url
                launch_args["proxy_username"] = parsed.username
                launch_args["proxy_password"] = parsed.password

            if _cloakbrowser is not None:
                try:
                    launch = getattr(_cloakbrowser, "launch", None)
                    if launch is None:
                        raise RuntimeError("cloakbrowser has no launch()")

                    # If launch is async, await it; otherwise run in thread
                    if inspect.iscoroutinefunction(launch):
                        self.browser = await launch(**launch_args)
                    else:
                        self.browser = await asyncio.to_thread(launch, **launch_args)

                    logger.info("Cloakbrowser launched and initialized")
                    return
                except Exception as e:
                    logger.warning(f"Cloakbrowser launch failed, falling back to Playwright: {e}")

            # Fallback to Playwright if cloakbrowser isn't available or failed
            self.playwright = await async_playwright().start()
            
            browser_type = random.choice([
                self.playwright.chromium,
                self.playwright.firefox,
                self.playwright.webkit
            ])

            kwargs = launch_args.copy()
            # Playwright expects a proxy dict when provided
            if proxy_url:
                parsed = urlparse(proxy_url)
                kwargs["proxy"] = {
                    "server": proxy_url,
                    "username": parsed.username,
                    "password": parsed.password,
                }

            self.browser = await browser_type.launch(**kwargs)
            logger.info("Playwright browser initialized with stealth mode")
    
    async def close(self):
        """Close the browser and playwright"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.playwright = None
    
    def _get_browser_profile(self) -> Dict[str, Any]:
        """Get a random browser profile"""
        return random.choice(self.BROWSER_PROFILES)
    
    async def _create_context(self, profile: Dict[str, Any]) -> BrowserContext:
        """Create a new browser context with the given profile"""
        if self.browser is None:
            await self._initialize_browser()
        
        context = await self.browser.new_context(
            viewport=profile["viewport"],
            device_scale_factor=profile["device_scale_factor"],
            locale=profile["locale"],
            timezone_id=profile["timezone_id"],
            user_agent=profile["user_agent"],
            ignore_https_errors=True,
            # Add anti-detection properties
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "max-age=0",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            }
        )
        
        # Add JavaScript to mask automation detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
            
            window.chrome = {
                runtime: {},
            };
            
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({
                    query: () => Promise.resolve({ state: 1 }),
                }),
            });
        """)
        
        return context
    
    def _detect_anti_bot(self, page_content: str, url: str) -> bool:
        """
        Detect anti-bot measures in page content
        
        Returns:
            bool: True if anti-bot measures detected
        """
        for pattern in self.ANTI_BOT_PATTERNS:
            if pattern.lower() in page_content.lower():
                logger.warning(f"Anti-bot pattern detected: '{pattern}' on {url}")
                return True
        
        return False
    
    async def _random_delay(self, min_wait: int, max_wait: int):
        """Add random delay to mimic human behavior"""
        delay = random.uniform(min_wait, max_wait)
        logger.debug(f"Human-like delay: {delay:.2f}s")
        await asyncio.sleep(delay)
    
    async def get(self, url: str, source: str = "unknown", **kwargs) -> Dict[str, Any]:
        """
        Make an HTTP GET request using Playwright with stealth
        
        Args:
            url: URL to fetch
            source: Source name for logging
            **kwargs: Additional options
            
        Returns:
            Dict with 'text', 'status', 'url' keys
        """
        profile = self._get_browser_profile()
        retry_count = 0
        
        while retry_count <= self.max_retries:
            context = None
            page = None
            
            try:
                context = await self._create_context(profile)
                page = await context.new_page()
                
                # Set realistic page behavior
                await page.set_viewport_size({
                    "width": profile["viewport"]["width"],
                    "height": profile["viewport"]["height"]
                })
                
                # Add some delay before navigating
                await self._random_delay(self.retry_min_wait, self.retry_min_wait + 1)
                
                logger.info(f"Fetching {url} from {source} using {profile['name']}")
                
                # Navigate to the URL with timeout
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self.timeout
                )
                
                # Get page content
                page_content = await page.content()
                status_code = response.status if response else 200
                
                # Check for anti-bot patterns
                if self._detect_anti_bot(page_content, url):
                    logger.warning(f"Anti-bot measures detected, retrying (attempt {retry_count + 1}/{self.max_retries})")
                    retry_count += 1
                    
                    if retry_count <= self.max_retries:
                        # Use different profile for retry
                        profile = self._get_browser_profile()
                        await self._random_delay(
                            self.retry_min_wait + retry_count,
                            self.retry_max_wait
                        )
                        continue
                    else:
                        logger.error(f"Failed to bypass anti-bot after {self.max_retries} retries")
                        return {
                            "text": page_content,
                            "status": status_code,
                            "url": url,
                            "error": "Anti-bot protection detected"
                        }
                
                # Success
                logger.info(f"Successfully fetched {url} (status: {status_code})")
                return {
                    "text": page_content,
                    "status": status_code,
                    "url": str(page.url),
                }
                
            except asyncio.TimeoutError:
                logger.error(f"Request timeout for {url}")
                retry_count += 1
                if retry_count <= self.max_retries:
                    await self._random_delay(
                        self.retry_min_wait + retry_count,
                        self.retry_max_wait
                    )
                    continue
                else:
                    return {"text": "", "status": 408, "url": url, "error": "Timeout"}
                    
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                retry_count += 1
                if retry_count <= self.max_retries:
                    await self._random_delay(
                        self.retry_min_wait + retry_count,
                        self.retry_max_wait
                    )
                    continue
                else:
                    return {"text": "", "status": 500, "url": url, "error": str(e)}
                    
            finally:
                # Clean up
                if page:
                    try:
                        await page.close()
                    except:
                        pass
                if context:
                    try:
                        await context.close()
                    except:
                        pass
        
        # All retries exhausted
        return {
            "text": "",
            "status": 500,
            "url": url,
            "error": f"Failed after {self.max_retries} retries"
        }

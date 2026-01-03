import argparse
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
from playwright.sync_api import sync_playwright, Page, Browser
from playwright_stealth.stealth import Stealth
from typing import Set, List, Dict, Any


class AshleyFurnitureScraper:
    
    BASE_URL = "https://www.ashleyfurniture.com"
    DEFAULT_CATEGORY_URL = "https://www.ashleyfurniture.com/c/furniture/bedroom/beds/"
    PAGE_SIZE = 30
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.product_urls: Set[str] = set()
        self.variant_urls: Set[str] = set()
        
    def _dismiss_modals(self, page: Page) -> None:
        try:
            page.wait_for_timeout(2000)
            
            region_selectors = [
                'text="Ashley United States"',
                'button:has-text("United States")',
                '.modal-close',
                '[aria-label="Close"]',
            ]
            for selector in region_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=1000):
                        page.locator(selector).first.click()
                        page.wait_for_timeout(500)
                        break
                except:
                    continue
            
            promo_selectors = [
                'text="No Thank You"',
                'text="No thanks"',
                '.popup-close',
                'button[aria-label="Close dialog"]',
            ]
            for selector in promo_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=1000):
                        page.locator(selector).first.click()
                        page.wait_for_timeout(500)
                        break
                except:
                    continue
            
            cookie_selectors = [
                '#onetrust-accept-btn-handler',
                'text="Accept All Cookies"',
                'button:has-text("Accept")',
            ]
            for selector in cookie_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=1000):
                        page.locator(selector).first.click()
                        page.wait_for_timeout(500)
                        break
                except:
                    continue
                    
            try:
                close_btn = page.locator('.modal-header .close, [aria-label="Close"]')
                if close_btn.first.is_visible(timeout=500):
                    close_btn.first.click()
                    page.wait_for_timeout(300)
            except:
                pass
                
        except Exception as e:
            print(f"Note: Modal dismissal encountered issue: {e}")
    
    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        if 'dwvar_' in url:
            params = parse_qs(parsed.query)
            variant_params = {k: v for k, v in params.items() if k.startswith('dwvar_')}
            if variant_params:
                query = urlencode(variant_params, doseq=True)
                return f"{self.BASE_URL}{parsed.path}?{query}"
        return f"{self.BASE_URL}{parsed.path}"
    
    def _extract_product_count(self, page: Page) -> int:
        try:
            pagination_text = page.evaluate("""
                () => {
                    const pag = document.querySelector('.pagination');
                    return pag ? pag.innerText : '';
                }
            """)
            
            if pagination_text:
                match = re.search(r'of\s+(\d+)', pagination_text.replace(',', ''))
                if match:
                    return int(match.group(1))
            
            content = page.content()
            match = re.search(r'"totalResults"\s*:\s*(\d+)', content)
            if match:
                return int(match.group(1))
            
            match = re.search(r'(\d+)\s*(?:Results|Products|Items)', content, re.IGNORECASE)
            if match:
                return int(match.group(1))
                
            return 0
        except Exception as e:
            print(f"Warning: Could not extract product count: {e}")
            return 0
    
    def _extract_urls_from_page(self, page: Page) -> None:
        try:
            page.wait_for_timeout(1500)
            
            try:
                page.wait_for_selector('.product-tile, a[href*="/p/"]', timeout=8000)
            except:
                pass
            
            product_links = page.evaluate("""
                () => {
                    const urls = new Set();
                    document.querySelectorAll('a[href*="/p/"]').forEach(a => {
                        if (a.href && !a.href.includes('javascript:')) {
                            urls.add(a.href);
                        }
                    });
                    return Array.from(urls);
                }
            """)
            
            for url in product_links:
                normalized = self._normalize_url(url)
                if 'dwvar_' in normalized:
                    self.variant_urls.add(normalized)
                else:
                    self.product_urls.add(normalized)
            
            swatch_links = page.evaluate("""
                () => {
                    const urls = [];
                    document.querySelectorAll('[data-url], [data-href], [data-swatch-url]').forEach(el => {
                        const url = el.getAttribute('data-url') || el.getAttribute('data-href') || el.getAttribute('data-swatch-url');
                        if (url && url.includes('/p/')) {
                            urls.push(url);
                        }
                    });
                    return urls;
                }
            """)
            
            for url in swatch_links:
                if url.startswith('/'):
                    url = f"{self.BASE_URL}{url}"
                normalized = self._normalize_url(url)
                self.variant_urls.add(normalized)
                
        except Exception as e:
            print(f"Warning: Error extracting URLs from page: {e}")
    
    def scrape(self, category_url: str = None) -> Dict[str, Any]:
        url = category_url or self.DEFAULT_CATEGORY_URL
        
        print(f"Starting Ashley Furniture scraper for: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                java_script_enabled=True,
                bypass_csp=True,
            )
            
            page = context.new_page()
            
            stealth_obj = Stealth()
            stealth_obj.apply_stealth_sync(page)
            
            try:
                print("Loading initial page...")
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        page.goto(url, wait_until='domcontentloaded', timeout=90000)
                        page.wait_for_timeout(3000)
                        break
                    except Exception as e:
                        if attempt < max_retries - 1:
                            print(f"Retry {attempt + 1}/{max_retries} after error: {e}")
                            time.sleep(2)
                        else:
                            raise
                
                self._dismiss_modals(page)
                
                total_products = self._extract_product_count(page)
                print(f"Total products found: {total_products}")
                
                if total_products == 0:
                    total_products = 500
                
                total_pages = (total_products + self.PAGE_SIZE - 1) // self.PAGE_SIZE
                print(f"Estimated pages to scrape: {total_pages}")
                
                print("Scraping page 1...")
                self._extract_urls_from_page(page)
                
                for page_num in range(1, total_pages):
                    start = page_num * self.PAGE_SIZE
                    paginated_url = f"{url}?start={start}&sz={self.PAGE_SIZE}"
                    
                    print(f"Scraping page {page_num + 1} (start={start})...")
                    
                    try:
                        page.goto(paginated_url, wait_until='domcontentloaded', timeout=60000)
                        page.wait_for_timeout(2000)
                        self._dismiss_modals(page)
                        self._extract_urls_from_page(page)
                        
                        time.sleep(1.5)
                        
                    except Exception as e:
                        print(f"Warning: Error on page {page_num + 1}: {e}")
                        time.sleep(2)
                        continue
                    
                    if (page_num + 1) % 5 == 0:
                        print(f"Progress: {len(self.product_urls)} products, {len(self.variant_urls)} variants so far")
                
            finally:
                browser.close()
        
        all_urls = sorted(self.product_urls | self.variant_urls)
        
        result = {
            "source": url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "product_urls": all_urls,
            "stats": {
                "total_urls": len(all_urls),
                "base_products": len(self.product_urls),
                "variant_urls": len(self.variant_urls)
            }
        }
        
        print(f"\nScraping complete!")
        print(f"Total unique URLs: {len(all_urls)}")
        print(f"Base products: {len(self.product_urls)}")
        print(f"Variant URLs: {len(self.variant_urls)}")
        
        return result


def main():
    parser = argparse.ArgumentParser(description='Ashley Furniture URL Discovery Scraper')
    parser.add_argument('--url', default=AshleyFurnitureScraper.DEFAULT_CATEGORY_URL)
    parser.add_argument('--output', default='../ashley_output.json')
    parser.add_argument('--headless', action='store_true', default=True)
    parser.add_argument('--no-headless', action='store_true')
    
    args = parser.parse_args()
    
    headless = not args.no_headless
    
    scraper = AshleyFurnitureScraper(headless=headless)
    result = scraper.scrape(args.url)
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\nOutput written to: {args.output}")


if __name__ == '__main__':
    main()

import argparse
import json
import re
import time
import itertools
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from playwright.sync_api import sync_playwright, Page, Browser
from typing import Set, List, Dict, Any, Optional, Tuple


class BizayScraper:
    
    BASE_URL = "https://us.bizay.com"
    DEFAULT_PRODUCT_URL = (
        "https://us.bizay.com/en-us/business-cards-2?"
        "id=443495438&spf0=1411&spf1=1390&spf2=1391&spf3=1419&"
        "productGroupId=1386&indexManagementId=3"
    )
    
    SPF_PARAMS = ['spf0', 'spf1', 'spf2', 'spf3']
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None
        
    def _dismiss_notifications(self, page: Page) -> None:
        try:
            page.wait_for_timeout(2000)
            
            consent_selectors = [
                'text="I accept"',
                'text="Accept"',
                'text="Accept All"',
                '#accept-cookies',
                '.cookie-accept',
            ]
            for selector in consent_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=1000):
                        page.locator(selector).first.click()
                        page.wait_for_timeout(500)
                        break
                except:
                    continue
                    
        except Exception as e:
            print(f"Note: Notification dismissal: {e}")
    
    def _parse_url_params(self, url: str) -> Dict[str, str]:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        return {k: v[0] if v else '' for k, v in params.items()}
    
    def _build_url_with_params(self, base_url: str, params: Dict[str, str]) -> str:
        parsed = urlparse(base_url)
        query = urlencode(params)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', query, ''))
    
    def _extract_product_metadata(self, page: Page, url_params: Dict) -> Dict[str, Any]:
        metadata = {
            "id": url_params.get('id'),
            "product_group_id": url_params.get('productGroupId'),
            "title": None,
            "subtitle": None,
            "description": None,
            "currency": "USD",
            "image_urls": [],
            "base_uom": None
        }
        
        try:
            title_sel = page.locator('h1, .product-title, .page-title').first
            if title_sel.is_visible(timeout=2000):
                metadata['title'] = title_sel.inner_text().strip()
            
            images = page.evaluate("""
                () => {
                    const imgs = [];
                    document.querySelectorAll('.product-image img, .gallery img, [class*="product"] img').forEach(img => {
                        if (img.src && !img.src.includes('data:') && img.naturalWidth > 50) {
                            imgs.push(img.src);
                        }
                    });
                    return [...new Set(imgs)].slice(0, 5);
                }
            """)
            metadata['image_urls'] = images
            
            uom_match = page.evaluate("""
                () => {
                    const text = document.body.innerText;
                    const match = text.match(/(\\d+)\\s*(cards?|units?|pieces?)/i);
                    return match ? match[2].toLowerCase().replace(/s$/, '') : null;
                }
            """)
            metadata['base_uom'] = uom_match or 'unit'
            
        except Exception as e:
            print(f"Warning: Error extracting metadata: {e}")
        
        return metadata
    
    def _discover_options(self, page: Page, base_url: str, current_params: Dict) -> List[Dict[str, Any]]:
        options = []
        
        spf_names = {
            'spf0': {'name': 'Product Type', 'key': 'product_type'},
            'spf1': {'name': 'Shape', 'key': 'shape'},
            'spf2': {'name': 'Size', 'key': 'size'},
            'spf3': {'name': 'Material', 'key': 'paper_stock'},
        }
        
        print("Discovering option values...")
        
        for spf_param, info in spf_names.items():
            option_group = {
                'name': info['name'],
                'key': info['key'],
                'spf_param': spf_param,
                'values': []
            }
            
            try:
                option_values = page.evaluate(f"""
                    () => {{
                        const values = [];
                        const containers = document.querySelectorAll(
                            '.option-group, .sku-selector, .product-option, ' +
                            '[class*="option"], [class*="selector"], tr, .row'
                        );
                        
                        const keywords = {{
                            'spf0': ['Standard', 'Die Cut', 'Folded', 'Business Cards'],
                            'spf1': ['Rectangle', 'Square', 'Rounded', 'Corners'],
                            'spf2': ['x', 'in', 'inch', '"', "'"],
                            'spf3': ['pt', 'lb', 'Paper', 'Cardstock', 'Gloss', 'Matte']
                        }};
                        
                        const paramKeywords = keywords['{spf_param}'] || [];
                        
                        document.querySelectorAll('*').forEach(el => {{
                            if (el.children.length === 0 && el.innerText) {{
                                const text = el.innerText.trim();
                                if (text.length > 2 && text.length < 100) {{
                                    const hasKeyword = paramKeywords.some(kw => 
                                        text.toLowerCase().includes(kw.toLowerCase())
                                    );
                                    if (hasKeyword) {{
                                        let current = el;
                                        for (let i = 0; i < 3; i++) {{
                                            if (!current) break;
                                            const id = current.getAttribute('data-id') || 
                                                      current.getAttribute('data-value') ||
                                                      current.id;
                                            if (id && /^\\d+$/.test(id)) {{
                                                values.push({{ value: text, id: id }});
                                                break;
                                            }}
                                            current = current.parentElement;
                                        }}
                                    }}
                                }}
                            }}
                        }});
                        
                        return values;
                    }}
                """)
                
                seen = set()
                for val in option_values:
                    key = f"{val['value']}_{val['id']}"
                    if key not in seen:
                        seen.add(key)
                        option_group['values'].append(val)
                
            except Exception as e:
                print(f"Warning: Could not discover options for {spf_param}: {e}")
            
            if option_group['values']:
                options.append(option_group)
        
        if len(options) < 2 or sum(len(o['values']) for o in options) < 4:
            print("Using predefined option values from site analysis...")
            options = self._get_predefined_options()
        
        return options
    
    def _get_predefined_options(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'Shape',
                'key': 'shape',
                'spf_param': 'spf1',
                'values': [
                    {'value': 'Rectangle', 'id': '1390'},
                    {'value': 'Rectangle | Rounded Corners', 'id': '1399'},
                ]
            },
            {
                'name': 'Size',
                'key': 'size',
                'spf_param': 'spf2',
                'values': [
                    {'value': '2 x 3.5 in', 'id': '1391'},
                    {'value': '2 x 2 in', 'id': '1406'},
                ]
            },
            {
                'name': 'Paper stock',
                'key': 'paper_stock',
                'spf_param': 'spf3',
                'values': [
                    {'value': '14pt Cardstock Gloss', 'id': '1419'},
                    {'value': '14pt Cardstock Matte', 'id': '1420'},
                    {'value': '14pt Cardstock High Gloss (UV)', 'id': '1421'},
                ]
            },
        ]
    
    def _extract_pricing(self, page: Page) -> List[Dict[str, Any]]:
        pricing = []
        
        try:
            page.wait_for_timeout(1500)
            
            pricing_data = page.evaluate("""
                () => {
                    const pricing = [];
                    
                    const rows = document.querySelectorAll(
                        'tr, .pricing-row, .quantity-row, [class*="price-row"]'
                    );
                    
                    rows.forEach(row => {
                        const text = row.innerText;
                        const qtyMatch = text.match(/(\\d{2,}|\\d+,\\d+)\\s*(?:units?|pcs?|cards?)?/i);
                        const priceMatch = text.match(/\\$([\\d,.]+)/);
                        
                        if (qtyMatch && priceMatch) {
                            const qty = parseInt(qtyMatch[1].replace(/,/g, ''));
                            const price = parseFloat(priceMatch[1].replace(/,/g, ''));
                            
                            if (qty >= 50 && price > 0 && qty < 100000) {
                                pricing.push({
                                    quantity: qty,
                                    total_price: price
                                });
                            }
                        }
                    });
                    
                    const tables = document.querySelectorAll('table');
                    tables.forEach(table => {
                        const cells = table.querySelectorAll('td');
                        for (let i = 0; i < cells.length - 1; i++) {
                            const qtyText = cells[i].innerText;
                            const priceText = cells[i + 1]?.innerText;
                            
                            if (qtyText && priceText) {
                                const qtyMatch = qtyText.match(/(\\d+)/);
                                const priceMatch = priceText.match(/\\$([\\d,.]+)/);
                                
                                if (qtyMatch && priceMatch) {
                                    const qty = parseInt(qtyMatch[1]);
                                    const price = parseFloat(priceMatch[1].replace(/,/g, ''));
                                    
                                    if (qty >= 50 && price > 0 && qty < 100000) {
                                        pricing.push({
                                            quantity: qty,
                                            total_price: price
                                        });
                                    }
                                }
                            }
                        }
                    });
                    
                    const mainPrice = document.querySelector('.current-price, .product-price, [class*="price"]');
                    if (mainPrice) {
                        const match = mainPrice.innerText.match(/\\$([\\d,.]+)/);
                        if (match) {
                            pricing.push({
                                quantity: null,
                                total_price: parseFloat(match[1].replace(/,/g, ''))
                            });
                        }
                    }
                    
                    return pricing;
                }
            """)
            
            seen = set()
            for p in pricing_data:
                if p['quantity'] and p['quantity'] not in seen:
                    seen.add(p['quantity'])
                    unit_price = round(p['total_price'] / p['quantity'], 4) if p['quantity'] else None
                    pricing.append({
                        'quantity': p['quantity'],
                        'unit_price': {
                            'amount': unit_price,
                            'currency': 'USD'
                        },
                        'total_price': {
                            'amount': p['total_price'],
                            'currency': 'USD'
                        }
                    })
            
            pricing.sort(key=lambda x: x['quantity'] or 0)
            
        except Exception as e:
            print(f"Warning: Error extracting pricing: {e}")
        
        return pricing
    
    def _scrape_variant(self, page: Page, base_url: str, base_params: Dict, 
                       selection: Dict[str, Dict]) -> Optional[Dict[str, Any]]:
        try:
            params = base_params.copy()
            for key, val in selection.items():
                if 'spf_param' in val:
                    params[val['spf_param']] = val['id']
            
            variant_url = self._build_url_with_params(base_url, params)
            
            page.goto(variant_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(2000)
            self._dismiss_notifications(page)
            
            page.wait_for_timeout(2000)
            
            pricing = self._extract_pricing(page)
            
            return {
                'sku': None,
                'available': len(pricing) > 0,
                'selection': {
                    k: {'value': v['value'], 'id': v['id']} 
                    for k, v in selection.items()
                },
                'pricing': pricing
            }
            
        except Exception as e:
            print(f"Warning: Error scraping variant: {e}")
            return None
    
    def scrape(self, product_url: str = None) -> Dict[str, Any]:
        url = product_url or self.DEFAULT_PRODUCT_URL
        
        print(f"Starting Bizay scraper for: {url}")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
            )
            
            page = context.new_page()
            
            try:
                url_params = self._parse_url_params(url)
                base_url = url.split('?')[0]
                
                print("Loading product page...")
                page.goto(url, wait_until='domcontentloaded', timeout=90000)
                page.wait_for_timeout(3000)
                self._dismiss_notifications(page)
                
                print("Extracting product metadata...")
                product = self._extract_product_metadata(page, url_params)
                
                print("Discovering product options...")
                options = self._discover_options(page, base_url, url_params)
                
                print(f"Found {len(options)} option groups:")
                for opt in options:
                    print(f"  - {opt['name']}: {len(opt['values'])} values")
                
                print("\nGenerating variant combinations...")
                
                option_value_lists = []
                for opt in options:
                    values_with_meta = []
                    for val in opt['values']:
                        values_with_meta.append({
                            'key': opt['key'],
                            'value': val['value'],
                            'id': val['id'],
                            'spf_param': opt.get('spf_param')
                        })
                    if values_with_meta:
                        option_value_lists.append(values_with_meta)
                
                all_combinations = list(itertools.product(*option_value_lists)) if option_value_lists else []
                
                print(f"Total variant combinations to scrape: {len(all_combinations)}")
                
                variants = []
                for i, combo in enumerate(all_combinations):
                    selection = {item['key']: item for item in combo}
                    
                    print(f"Scraping variant {i+1}/{len(all_combinations)}: ", end='')
                    print(', '.join(f"{k}={v['value']}" for k, v in selection.items()))
                    
                    variant = self._scrape_variant(page, base_url, url_params, selection)
                    if variant:
                        variants.append(variant)
                    
                    time.sleep(0.5)
                
                if not variants:
                    print("Getting pricing for current configuration...")
                    pricing = self._extract_pricing(page)
                    if pricing:
                        variants.append({
                            'sku': None,
                            'available': True,
                            'selection': {},
                            'pricing': pricing
                        })
                
            finally:
                browser.close()
        
        formatted_options = []
        for opt in options:
            formatted_options.append({
                'name': opt['name'],
                'key': opt['key'],
                'values': [{'value': v['value'], 'id': v['id']} for v in opt['values']]
            })
        
        result = {
            "source_url": url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "product": product,
            "options": formatted_options,
            "variants": variants
        }
        
        print(f"\nScraping complete!")
        print(f"Product: {product.get('title', 'Unknown')}")
        print(f"Options: {len(options)}")
        print(f"Variants with pricing: {len(variants)}")
        
        return result


def main():
    parser = argparse.ArgumentParser(description='Bizay Product + Variant Matrix Scraper')
    parser.add_argument('--url', default=BizayScraper.DEFAULT_PRODUCT_URL)
    parser.add_argument('--output', default='../bizay_output.json')
    parser.add_argument('--headless', action='store_true', default=True)
    parser.add_argument('--no-headless', action='store_true')
    
    args = parser.parse_args()
    
    headless = not args.no_headless
    
    scraper = BizayScraper(headless=headless)
    result = scraper.scrape(args.url)
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print(f"\nOutput written to: {args.output}")


if __name__ == '__main__':
    main()

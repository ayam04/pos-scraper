# Pos-Scraper

Two self-contained Python scrapers for extracting structured data from e-commerce sites.

## Project Structure

```
scraper/
├── ashley_scraper/           # Task 1: Ashley Furniture URL Discovery
│   ├── __init__.py
│   ├── scraper.py           # Main scraper script
│   └── requirements.txt
├── bizay_scraper/           # Task 2: Bizay Product Variants + Pricing
│   ├── __init__.py
│   ├── scraper.py           # Main scraper script
│   └── requirements.txt
├── ashley_output.json       # Generated output
├── bizay_output.json        # Generated output
└── README.md
```

## Prerequisites

- Python 3.8+
- pip

## Installation

```bash
# Install Playwright
pip install playwright python-dateutil

# Install Playwright browsers (required first time)
playwright install chromium
```

## Running the Scrapers

### Task 1: Ashley Furniture URL Discovery

Discovers all Product Detail Pages and Variant URLs from Ashley Furniture category pages.

```bash
cd ashley_scraper
python scraper.py
```

**Options:**
```bash
python scraper.py --help
python scraper.py --url "https://www.ashleyfurniture.com/c/furniture/living-room/sofas/"
python scraper.py --output custom_output.json
python scraper.py --no-headless  # Run with visible browser
```

**Output:** `ashley_output.json` with structure:
```json
{
  "source": "https://www.ashleyfurniture.com/c/furniture/bedroom/beds/",
  "collected_at": "2026-01-03T00:00:00Z",
  "product_urls": ["..."],
  "stats": { "total_urls": 470, "base_products": 400, "variant_urls": 70 }
}
```

---

### Task 2: Bizay Product + Variant Matrix

Extracts product details and all variant combinations with quantity-based pricing.

```bash
cd bizay_scraper
python scraper.py
```

**Options:**
```bash
python scraper.py --help
python scraper.py --url "https://us.bizay.com/en-us/..."
python scraper.py --output custom_output.json
python scraper.py --no-headless  # Run with visible browser
```

**Output:** `bizay_output.json` with structure:
```json
{
  "source_url": "https://us.bizay.com/...",
  "scraped_at": "2026-01-03T00:00:00Z",
  "product": { "id": "...", "title": "Business Cards", ... },
  "options": [ { "name": "Shape", "key": "shape", "values": [...] } ],
  "variants": [
    {
      "selection": { "shape": { "value": "Rectangle", "id": "1390" } },
      "pricing": [
        { "quantity": 100, "unit_price": {...}, "total_price": {...} }
      ]
    }
  ]
}
```

## Anti-Bot Handling

Both scrapers use:
- **Playwright** for headless browser automation
- Realistic browser user-agent and viewport
- Modal/popup dismissal (region selectors, promo popups, cookie banners)
- Polite delays between requests
- Error recovery and retry logic

## Testing on Other Categories/Products

Both scrapers accept `--url` parameter for testing on different pages:

```bash
# Ashley: Different category
python ashley_scraper/scraper.py --url "https://www.ashleyfurniture.com/c/furniture/dining-room/tables/"

# Bizay: Different product
python bizay_scraper/scraper.py --url "https://us.bizay.com/en-us/another-product?..."
```

## Troubleshooting

- **403 Errors**: The scrapers use Playwright; ensure `playwright install chromium` was run
- **Slow scraping**: Normal due to polite delays; use `--no-headless` to observe
- **Missing data**: Some sites may have anti-bot updates; run with `--no-headless` to debug

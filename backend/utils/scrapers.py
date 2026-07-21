import re
import requests
from bs4 import BeautifulSoup

def scrape_price(store: str, product: str) -> dict:
    """
    Scrapes or extracts a product price from store HTML content.
    Used for live lookup validation in pricing pipelines.
    """
    url = f"https://www.example.com/{store.lower()}/search?q={product}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    html = resp.text
    
    price = None
    
    # 1. Try extracting from JSON-like window.__INITIAL_STATE__
    json_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})', html)
    if json_match:
        try:
            import json
            data = json.loads(json_match.group(1))
            if "price" in data:
                price_str = data["price"]
                price_clean = re.sub(r'[^\d.]', '', price_str)
                if price_clean:
                    price = float(price_clean)
        except Exception:
            pass
            
    # 2. Try extracting from elements with 'price' class
    if price is None:
        soup = BeautifulSoup(html, "html.parser")
        price_elem = soup.find(class_="price")
        if price_elem:
            price_text = price_elem.get_text()
            price_clean = re.sub(r'[^\d.]', '', price_text)
            if price_clean:
                price = float(price_clean)
                
    # 3. Fallback regex search
    if price is None:
        price_match = re.search(r'\$?([0-9]+\.[0-9]+)', html)
        if price_match:
            price = float(price_match.group(1))
            
    return {
        "store": store,
        "product": product,
        "price": price,
        "source": "live"
    }

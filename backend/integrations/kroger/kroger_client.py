"""
kroger_client.py
Kroger Products API v1.3.0 integration for grocer-optimizer.

Auth:   OAuth2 Client Credentials (scope: product.compact)
Docs:   https://developer.kroger.com/api-products/api/product-api-public
Spec:   openapi.json (v1.3.0)

Usage:
    client = KrogerClient(client_id=..., client_secret=...)
    results = client.search_products(term="milk", location_id="01400943")
    product = client.get_product(product_id="0001111041700", location_id="01400943")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.kroger.com"
TOKEN_URL = f"{BASE_URL}/v1/connect/oauth2/token"
SEARCH_URL = f"{BASE_URL}/v1/products"
PRODUCT_URL = f"{BASE_URL}/v1/products/{{id}}"

SCOPE = "product.compact"
TOKEN_EXPIRY_BUFFER_SECONDS = 60  # refresh token this many seconds early


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ProductPrice:
    regular: Optional[float] = None
    promo: Optional[float] = None
    regular_per_unit: Optional[float] = None
    promo_per_unit: Optional[float] = None
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ProductPrice":
        return cls(
            regular=d.get("regular"),
            promo=d.get("promo"),
            regular_per_unit=d.get("regularPerUnitEstimate"),
            promo_per_unit=d.get("promoPerUnitEstimate"),
            effective_date=d.get("effectiveDate"),
            expiration_date=d.get("expirationDate"),
        )

    @property
    def current_price(self) -> Optional[float]:
        """Returns promo price if active, otherwise regular price."""
        return self.promo if self.promo else self.regular


@dataclass
class ProductItem:
    item_id: str
    size: Optional[str] = None
    sold_by: Optional[str] = None
    price: Optional[ProductPrice] = None
    national_price: Optional[ProductPrice] = None
    stock_level: Optional[str] = None  # e.g. "TEMPORARILY_OUT_OF_STOCK", "HIGH"
    in_store: bool = False
    curbside: bool = False
    delivery: bool = False
    ship_to_home: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "ProductItem":
        price_raw = d.get("price")
        national_price_raw = d.get("nationalPrice")
        inventory = d.get("inventory", {})
        fulfillment = d.get("fulfillment", {})
        return cls(
            item_id=d.get("itemId", ""),
            size=d.get("size"),
            sold_by=d.get("soldBy"),
            price=ProductPrice.from_dict(price_raw) if price_raw else None,
            national_price=ProductPrice.from_dict(national_price_raw) if national_price_raw else None,
            stock_level=inventory.get("stockLevel"),
            in_store=fulfillment.get("instore", False),
            curbside=fulfillment.get("curbside", False),
            delivery=fulfillment.get("delivery", False),
            ship_to_home=fulfillment.get("shiptohome", False),
        )


@dataclass
class Product:
    product_id: str
    description: str
    brand: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    upc: Optional[str] = None
    snap_eligible: bool = False
    items: list[ProductItem] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Product":
        return cls(
            product_id=d.get("productId", ""),
            description=d.get("description", ""),
            brand=d.get("brand"),
            categories=d.get("categories", []),
            upc=d.get("upc"),
            snap_eligible=d.get("snapEligible", False),
            items=[ProductItem.from_dict(i) for i in d.get("items", [])],
            images=d.get("images", []),
        )

    def best_price(self) -> Optional[ProductPrice]:
        """Returns the price from the first item that has one."""
        for item in self.items:
            if item.price:
                return item.price
        return None

    def to_normalized_dict(self) -> dict:
        """
        Returns a flat dict compatible with grocer-optimizer's
        product normalization pipeline.
        """
        price = self.best_price()
        first_item = self.items[0] if self.items else None
        return {
            "store": "kroger",
            "product_id": self.product_id,
            "upc": self.upc,
            "description": self.description,
            "brand": self.brand,
            "categories": self.categories,
            "size": first_item.size if first_item else None,
            "sold_by": first_item.sold_by if first_item else None,
            "regular_price": price.regular if price else None,
            "promo_price": price.promo if price else None,
            "current_price": price.current_price if price else None,
            "price_per_unit": price.regular_per_unit if price else None,
            "snap_eligible": self.snap_eligible,
            "in_store": first_item.in_store if first_item else False,
            "stock_level": first_item.stock_level if first_item else None,
        }


# ---------------------------------------------------------------------------
# Token manager
# ---------------------------------------------------------------------------

class _TokenManager:
    """Handles OAuth2 client credentials token lifecycle."""

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        return self._refresh()

    def _refresh(self) -> str:
        logger.debug("Refreshing Kroger OAuth2 token")
        resp = httpx.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": SCOPE},
            auth=(self._client_id, self._client_secret),
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 1800)
        self._expires_at = time.time() + expires_in - TOKEN_EXPIRY_BUFFER_SECONDS
        logger.debug("Token refreshed, expires in %ds", expires_in)
        return self._access_token


# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------

class KrogerClient:
    """
    Thin, production-ready client for the Kroger Products API v1.3.0.

    Args:
        client_id:     Your Kroger API client_id.
        client_secret: Your Kroger API client_secret.
        timeout:       HTTP timeout in seconds (default: 10).
        max_retries:   Number of retries on transient errors (default: 3).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        timeout: int = 10,
        max_retries: int = 3,
    ):
        self._tokens = _TokenManager(client_id, client_secret)
        self._timeout = timeout
        self._max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_products(
        self,
        *,
        term: Optional[str] = None,
        product_id: Optional[str] = None,
        location_id: Optional[str] = None,
        brand: Optional[str] = None,
        fulfillment: Optional[str] = None,  # "ais" | "csp" | "dth" | "sth"
        start: int = 0,
        limit: int = 10,
    ) -> list[Product]:
        """
        Search for products. Either `term` or `product_id` is required.

        Args:
            term:        Search term (e.g. "milk", "bread").
            product_id:  Specific product ID or comma-separated list.
            location_id: Kroger store location ID — required for pricing.
            brand:       Filter by brand name.
            fulfillment: Filter by fulfillment type ("ais"=in-store, "csp"=curbside,
                         "dth"=delivery, "sth"=ship-to-home).
            start:       Pagination offset.
            limit:       Max results (max 50 per Kroger's API).

        Returns:
            List of Product objects, empty list if none found.

        Raises:
            ValueError:  If neither term nor product_id is provided.
            httpx.HTTPStatusError: On non-retryable API errors.
        """
        if not term and not product_id:
            raise ValueError("Either `term` or `product_id` is required.")

        params: dict = {"filter.start": start, "filter.limit": limit}
        if term:
            params["filter.term"] = term
        if product_id:
            params["filter.productId"] = product_id
        if location_id:
            params["filter.locationId"] = location_id
        if brand:
            params["filter.brand"] = brand
        if fulfillment:
            params["filter.fulfillment"] = fulfillment

        data = self._get(SEARCH_URL, params=params)
        return [Product.from_dict(p) for p in data.get("data", [])]

    def get_product(
        self,
        product_id: str,
        location_id: Optional[str] = None,
    ) -> Optional[Product]:
        """
        Fetch details for a single product by ID.

        Args:
            product_id:  Kroger product ID.
            location_id: Store location ID — required for store-specific pricing.

        Returns:
            Product object, or None if not found.
        """
        url = PRODUCT_URL.format(id=product_id)
        params = {}
        if location_id:
            params["filter.locationId"] = location_id
        try:
            data = self._get(url, params=params)
            return Product.from_dict(data.get("data", {}))
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def search_normalized(
        self,
        term: str,
        location_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Convenience wrapper: search and return flat normalized dicts
        ready for grocer-optimizer's normalization pipeline.
        """
        products = self.search_products(term=term, location_id=location_id, limit=limit)
        return [p.to_normalized_dict() for p in products]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict = None) -> dict:
        """GET with auth headers and retry logic."""
        last_exc = None
        for attempt in range(1, self._max_retries + 1):
            try:
                token = self._tokens.get_token()
                resp = httpx.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                # 401 = token expired mid-flight, force refresh and retry once
                if e.response.status_code == 401 and attempt == 1:
                    logger.warning("401 received, forcing token refresh")
                    self._tokens._expires_at = 0
                    last_exc = e
                    continue
                # 429 = rate limited, back off
                if e.response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning("Rate limited (429), retrying in %ds", wait)
                    time.sleep(wait)
                    last_exc = e
                    continue
                raise
            except httpx.TransientError as e:
                wait = 2 ** attempt
                logger.warning("Transient error on attempt %d, retrying in %ds: %s", attempt, wait, e)
                time.sleep(wait)
                last_exc = e
        raise last_exc


# ---------------------------------------------------------------------------
# Example usage / quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.DEBUG)

    client = KrogerClient(
        client_id=os.environ["KROGER_CLIENT_ID"],
        client_secret=os.environ["KROGER_CLIENT_SECRET"],
    )

    # Search for milk — pass a location_id to get store-specific pricing
    # Find location IDs via the Kroger Locations API:
    # GET https://api.kroger.com/v1/locations?filter.zipCode=43040&filter.radiusInMiles=10
    LOCATION_ID = os.environ.get("KROGER_LOCATION_ID", "")

    print("\n--- Searching for 'milk' ---")
    results = client.search_normalized("milk", location_id=LOCATION_ID or None, limit=5)
    for r in results:
        print(r)

    if results:
        pid = results[0]["product_id"]
        print(f"\n--- Fetching product details for {pid} ---")
        product = client.get_product(pid, location_id=LOCATION_ID or None)
        if product:
            print(product.to_normalized_dict())

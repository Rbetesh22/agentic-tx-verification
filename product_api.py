"""
A mock product API that simulates fetching products from a real-world e-commerce backend.
This provides a more realistic data source for the ShoppingAgent.
"""

import random
from typing import Dict, List, Optional

# A larger, more diverse product catalog to simulate a real API
# Prices are varied to allow for more dynamic budget-based searches.
SIMULATED_PRODUCT_DATABASE = {
    "t-shirt": [
        {"id": "ts001", "name": "Classic Crewneck T-Shirt", "brand": "Everlane", "price": 25.00, "category": "tops", "style": "casual", "sizes": ["S", "M", "L", "XL"]},
        {"id": "ts002", "name": "V-Neck Supima Cotton Tee", "brand": "Uniqlo", "price": 19.90, "category": "tops", "style": "casual", "sizes": ["M", "L"]},
        {"id": "ts003", "name": "Graphic Print T-Shirt", "brand": "Zara", "price": 35.50, "category": "tops", "style": "casual", "sizes": ["S", "M"]},
        {"id": "ts004", "name": "Performance Sport Tee", "brand": "Nike", "price": 45.00, "category": "tops", "style": "athletic", "sizes": ["M", "L", "XL"]},
    ],
    "jeans": [
        {"id": "jn001", "name": "Slim Fit Selvedge Jeans", "brand": "J.Crew", "price": 128.00, "category": "bottoms", "style": "casual", "sizes": ["30", "32", "34"]},
        {"id": "jn002", "name": "Relaxed Straight Leg Jeans", "brand": "Levi's", "price": 89.50, "category": "bottoms", "style": "casual", "sizes": ["32", "34", "36"]},
        {"id": "jn003", "name": "Black Skinny Jeans", "brand": "ASOS", "price": 55.00, "category": "bottoms", "style": "casual", "sizes": ["30", "32"]},
        {"id": "jn004", "name": "Distressed Denim", "brand": "H&M", "price": 49.99, "category": "bottoms", "style": "casual", "sizes": ["32"]},
    ],
    "shirt": [
        {"id": "sh001", "name": "Oxford Button-Down Shirt", "brand": "Brooks Brothers", "price": 140.00, "category": "tops", "style": "formal", "sizes": ["M", "L"]},
        {"id": "sh002", "name": "Linen Long-Sleeve Shirt", "brand": "Banana Republic", "price": 89.00, "category": "tops", "style": "casual", "sizes": ["S", "M", "L"]},
        {"id": "sh003", "name": "Flannel Plaid Shirt", "brand": "Patagonia", "price": 99.00, "category": "tops", "style": "casual", "sizes": ["L", "XL"]},
    ],
    "sneakers": [
        {"id": "sn001", "name": "Leather Court Sneakers", "brand": "Common Projects", "price": 425.00, "category": "shoes", "style": "casual", "sizes": ["9", "10", "11"]},
        {"id": "sn002", "name": "Retro Runner", "brand": "New Balance", "price": 110.00, "category": "shoes", "style": "athletic", "sizes": ["10", "11"]},
        {"id": "sn003", "name": "Canvas Low-Tops", "brand": "Converse", "price": 60.00, "category": "shoes", "style": "casual", "sizes": ["9", "10"]},
    ],
    "dress-shoes": [
        {"id": "ds001", "name": "Wingtip Oxfords", "brand": "Allen Edmonds", "price": 395.00, "category": "shoes", "style": "formal", "sizes": ["9", "10", "11"]},
        {"id": "ds002", "name": "Leather Loafers", "brand": "Gucci", "price": 890.00, "category": "shoes", "style": "formal", "sizes": ["10"]},
    ],
}


class ProductAPI:
    """A class to simulate a product search API."""

    def search(
        self,
        query: str,
        style: Optional[str] = None,
        size: Optional[str] = None,
        max_price: Optional[float] = None,
        min_price: Optional[float] = 0,
        max_results: int = 10,
    ) -> List[Dict]:
        """
        Simulates searching for products in a database.

        Args:
            query: A search string (e.g., "t-shirt", "jeans").
            style: "casual", "formal", or "athletic".
            size: Desired size.
            max_price: Maximum price for an item.
            min_price: Minimum price for an item.
            max_results: The maximum number of results to return.

        Returns:
            A list of product dictionaries matching the criteria.
        """
        query_words = set(query.lower().split())
        results = []

        # Flatten all products into a single list for searching
        all_products = [item for sublist in SIMULATED_PRODUCT_DATABASE.values() for item in sublist]
        random.shuffle(all_products)

        for product in all_products:
            name_set = set(product["name"].lower().split())
            brand_set = set(product["brand"].lower().split())
            
            # Basic keyword matching on name and brand
            if not query_words.intersection(name_set | brand_set):
                # If the query is a known category, match it
                if not any(q in product["name"] for q in query_words) and product["category"] not in query_words:
                    continue

            # Filter by style
            if style and product.get("style") != style:
                continue

            # Filter by price
            if max_price is not None and product["price"] > max_price:
                continue
            if min_price is not None and product["price"] < min_price:
                continue

            # Filter by size
            if size and "sizes" in product and size not in product["sizes"]:
                continue
            
            # Add a formatted link
            product_with_link = product.copy()
            product_with_link["link"] = f"https://example.com/products/{product['id']}"
            results.append(product_with_link)

            if len(results) >= max_results:
                break
        
        # Sort results by a simulated "relevance" score (here, just price)
        results.sort(key=lambda p: p["price"])

        return results

# Global instance of the API
PRODUCT_API = ProductAPI()

"""
Shopping agent that searches for products matching user preferences.
Uses realistic product data from major retailers.
"""

import random
import time
from typing import Dict, List


# Real products from major retailers - curated catalog
PRODUCT_CATALOG = {
    # Casual T-shirts
    ("casual", "tops"): [
        {"name": "Uniqlo Airism T-Shirt", "brand": "Uniqlo", "price": 14.99, "size": "M", "link": "uniqlo.com/airism-tshirt"},
        {"name": "H&M Basic Cotton Tee", "brand": "H&M", "price": 9.99, "size": "M", "link": "hm.com/basics"},
        {"name": "Gap Crew Neck T-Shirt", "brand": "Gap", "price": 19.99, "size": "L", "link": "gap.com/tshirts"},
        {"name": "Target Goodfellow Tee", "brand": "Target", "price": 7.99, "size": "M", "link": "target.com/goodfellow"},
        {"name": "Banana Republic Luxe Touch Tee", "brand": "Banana Republic", "price": 39.99, "size": "M", "link": "bananarepublic.com"},
    ],
    # Formal/Business Casual
    ("formal", "tops"): [
        {"name": "Brooks Brothers Oxford Button-Down", "brand": "Brooks Brothers", "price": 89.00, "size": "M", "link": "brooksbrothers.com/oxford"},
        {"name": "J.Crew Factory Flex Chino Shirt", "brand": "J.Crew", "price": 49.50, "size": "M", "link": "jcreeffactory.com"},
        {"name": "Ralph Lauren Polo Shirt", "brand": "Ralph Lauren", "price": 65.00, "size": "L", "link": "ralphlauren.com/polo"},
        {"name": "ASOS Men's Smart Shirt", "brand": "ASOS", "price": 35.00, "size": "M", "link": "asos.com/shirts"},
    ],
    # Jeans
    ("casual", "bottoms"): [
        {"name": "Levi's 501 Original Fit", "brand": "Levi's", "price": 79.99, "size": "32", "link": "levis.com/501"},
        {"name": "GAP 1969 Jeans", "brand": "Gap", "price": 69.99, "size": "32", "link": "gap.com/1969"},
        {"name": "Amazon Essentials Denim", "brand": "Amazon", "price": 34.99, "size": "34", "link": "amazon.com/essentials-jeans"},
        {"name": "Old Navy Straight Jeans", "brand": "Old Navy", "price": 44.99, "size": "32", "link": "oldnavy.com"},
        {"name": "ASOS Slim Black Denim", "brand": "ASOS", "price": 55.00, "size": "30", "link": "asos.com/denim"},
    ],
    # Formal/Work Pants
    ("formal", "bottoms"): [
        {"name": "Dockers Khaki Pants", "brand": "Dockers", "price": 49.99, "size": "32", "link": "dockers.com/khaki"},
        {"name": "J.Crew Factory Sutton Trouser", "brand": "J.Crew", "price": 59.50, "size": "32", "link": "jcreuffactory.com"},
        {"name": "Banana Republic Sloan Pant", "brand": "Banana Republic", "price": 79.99, "size": "30", "link": "bananarepublic.com/sloan"},
        {"name": "Calvin Klein Slim Trousers", "brand": "Calvin Klein", "price": 74.99, "size": "34", "link": "calvinklein.com/trousers"},
    ],
    # Hoodies/Sweatshirts
    ("casual", "outerwear"): [
        {"name": "Gildan Heavy Blend Hoodie", "brand": "Gildan", "price": 29.99, "size": "M", "link": "gildan.com/hoodie"},
        {"name": "Champion Pullover Hoodie", "brand": "Champion", "price": 59.99, "size": "L", "link": "champion.com/hoodie"},
        {"name": "Nike Sportswear Club Hoodie", "brand": "Nike", "price": 74.97, "size": "M", "link": "nike.com/hoodie"},
        {"name": "Adidas Essentials Linear Hoodie", "brand": "Adidas", "price": 69.99, "size": "M", "link": "adidas.com/hoodie"},
        {"name": "Carhartt Work Hoodie", "brand": "Carhartt", "price": 59.99, "size": "L", "link": "carhartt.com/hoodie"},
    ],
    # Formal/Dress
    ("formal", "outerwear"): [
        {"name": "Dockers Modern Blazer", "brand": "Dockers", "price": 99.99, "size": "40", "link": "dockers.com/blazer"},
        {"name": "J.Crew Thompson Sport Coat", "brand": "J.Crew", "price": 198.00, "size": "40", "link": "jcrew.com/blazer"},
        {"name": "Banana Republic Tailored Blazer", "brand": "Banana Republic", "price": 179.99, "size": "40", "link": "bananarepublic.com/blazer"},
    ],
    # Sneakers/Athletic
    ("casual", "shoes"): [
        {"name": "Nike Air Force 1", "brand": "Nike", "price": 109.99, "size": "10", "link": "nike.com/af1"},
        {"name": "Adidas Stan Smith", "brand": "Adidas", "price": 89.99, "size": "10", "link": "adidas.com/stansmith"},
        {"name": "Converse Chuck Taylor All Star", "brand": "Converse", "price": 54.99, "size": "10", "link": "converse.com/chucktaylor"},
        {"name": "Puma Court Legacy", "brand": "Puma", "price": 79.99, "size": "10", "link": "puma.com/court"},
        {"name": "Amazon Generic Sneaker", "brand": "Amazon", "price": 34.99, "size": "10", "link": "amazon.com/sneakers"},
    ],
    # Formal/Dress Shoes
    ("formal", "shoes"): [
        {"name": "Cole Haan Oxford Shoes", "brand": "Cole Haan", "price": 149.99, "size": "10", "link": "colehaan.com/oxford"},
        {"name": "Allen Edmonds Park Avenue", "brand": "Allen Edmonds", "price": 395.00, "size": "10", "link": "allenedmonds.com"},
        {"name": "Dockers Leather Loafer", "brand": "Dockers", "price": 79.99, "size": "10", "link": "dockers.com/loafer"},
    ],
    # Accessories
    ("casual", "accessories"): [
        {"name": "Nike Everyday Socks (6-pack)", "brand": "Nike", "price": 14.99, "size": "OS", "link": "nike.com/socks"},
        {"name": "Fossil Leather Belt", "brand": "Fossil", "price": 48.00, "size": "M", "link": "fossil.com/belt"},
        {"name": "Amazon Essentials Cotton Socks", "brand": "Amazon", "price": 11.99, "size": "OS", "link": "amazon.com/socks"},
        {"name": "Timex Watch", "brand": "Timex", "price": 67.99, "size": "OS", "link": "timex.com/watch"},
        {"name": "J.Crew Factory Wool Scarf", "brand": "J.Crew", "price": 34.99, "size": "OS", "link": "jcreuffactory.com/scarf"},
    ],
}


class ShoppingAgent:
    """Agent that searches for products matching user preferences."""

    def __init__(self):
        self.search_history = []

    def search_products(
        self,
        budget: float,
        style: str,
        size: str,
        occasion: str = None,
        max_results: int = 5,
    ) -> List[Dict]:
        """
        Search for products matching user preferences.
        
        Args:
            budget: Maximum price per item
            style: "casual" or "formal"
            size: Clothing size (e.g., "M", "L", "32")
            occasion: Optional occasion context
            max_results: Maximum number of items to return
            
        Returns:
            List of matching product dictionaries
        """
        results = []
        
        # Search through relevant categories
        for (cat_style, cat_type), products in PRODUCT_CATALOG.items():
            if cat_style == style:
                for product in products:
                    # Check if price is within budget
                    if product["price"] <= budget:
                        # Prefer matching sizes or general sizes
                        if size in [product["size"], "OS"] or size in ["M", "L", "32", "34", "40"]:
                            results.append(product)
        
        # Sort by price first, then sample from top candidates for variety.
        results.sort(key=lambda x: x["price"])
        candidate_pool = results[: max_results * 2]
        if len(candidate_pool) > max_results:
            results = random.sample(candidate_pool, k=max_results)
            results.sort(key=lambda x: x["price"])
        else:
            results = candidate_pool

        for product in results:
            if not str(product.get("link", "")).startswith("http"):
                product["link"] = f"https://{product['link']}"
        
        # Record search
        self.search_history.append({
            "ts": time.time(),
            "budget": budget,
            "style": style,
            "size": size,
            "results_count": len(results),
        })
        
        return results

    def get_search_stats(self) -> Dict:
        """Get agent search statistics."""
        if not self.search_history:
            return {"searches": 0, "total_budget_queried": 0.0, "avg_results": 0.0}
        
        total_budget = sum(s["budget"] for s in self.search_history)
        total_results = sum(s["results_count"] for s in self.search_history)
        
        return {
            "searches": len(self.search_history),
            "total_budget_queried": total_budget,
            "avg_results": total_results / len(self.search_history) if self.search_history else 0,
            "last_search": self.search_history[-1]["ts"] if self.search_history else None,
        }


# Global agent instance
AGENT = ShoppingAgent()

# utils/pricing.py

class PricingUtil:
    @staticmethod
    def calculate_combination_price(product, quantity: int) -> float:
        
        if not product or not quantity:
            return 0.0

        selling_price = float(product.selling_price or 0)
        combination_size = product.combination_size or 0
        combination_price = float(product.combination_price or 0)

        # If no combination logic set, fallback to standard pricing
        if combination_size <= 1 or combination_price <= 0:
            return round(selling_price * quantity, 2)

        # Apply combination-first logic
        full_combos = quantity // combination_size
        remaining_units = quantity % combination_size

        # Cost of full combos
        combo_cost = full_combos * combination_price

        # Option 1: remainder priced normally
        remainder_cost = remaining_units * selling_price

        # Option 2: treat remaining as extra combo (but only if cheaper)
        extra_combo_cost = combination_price if remaining_units else 0

        if remaining_units:
            remainder_cost = min(remainder_cost, extra_combo_cost)

        total_price = combo_cost + remainder_cost
        return round(total_price, 2)

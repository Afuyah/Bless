class CheckoutService {
    constructor(shopId) {
        this.shopId = shopId;
        this.cartService = new CartService(shopId);
    }

    async processCheckout(paymentMethod, customerName = null) {
        const cart = this.cartService.getCart();
        
        if (cart.length === 0) {
            throw new Error('Cannot checkout with empty cart');
        }

        try {
            const response = await fetch(`/shops/${this.shopId}/checkout`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
                },
                body: JSON.stringify({
                    payment_method: paymentMethod,
                    customer_name: customerName,
                    cart: cart
                })
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Checkout failed');
            }

            const result = await response.json();
            this.cartService.clearCart();
            return result;
        } catch (error) {
            console.error('Checkout error:', error);
            throw error;
        }
    }
}
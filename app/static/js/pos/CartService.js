class CartService {
    constructor(shopId) {
        this.shopId = shopId;
        this.cartKey = `cart_${shopId}`;
    }

    getCart() {
        const cart = localStorage.getItem(this.cartKey);
        return cart ? JSON.parse(cart) : [];
    }

    addItem(product, quantity) {
        const cart = this.getCart();
        
        // Check if product already in cart
        const existingItem = cart.find(item => item.product_id === product.id);
        
        if (existingItem) {
            existingItem.quantity += quantity;
            existingItem.subtotal = this.calculateSubtotal(product, existingItem.quantity);
        } else {
            cart.push({
                product_id: product.id,
                product_name: product.name,
                quantity: quantity,
                unit_price: product.selling_price,
                combination_price: product.combination_price,
                combination_size: product.combination_size,
                subtotal: this.calculateSubtotal(product, quantity)
            });
        }
        
        this.saveCart(cart);
        return cart;
    }

    removeItem(productId) {
        const cart = this.getCart().filter(item => item.product_id !== productId);
        this.saveCart(cart);
        return cart;
    }

    clearCart() {
        localStorage.removeItem(this.cartKey);
        return [];
    }

    calculateSubtotal(product, quantity) {
        if (!product.combination_size || quantity < product.combination_size) {
            return product.selling_price * quantity;
        }
        
        const fullCombinations = Math.floor(quantity / product.combination_size);
        const remainder = quantity % product.combination_size;
        
        return (fullCombinations * product.combination_price) + 
               (remainder * product.selling_price);
    }

    saveCart(cart) {
        localStorage.setItem(this.cartKey, JSON.stringify(cart));
        this.updateCartUI(cart);
    }

    updateCartUI(cart) {
        // Dispatch custom event or update DOM directly
        document.dispatchEvent(new CustomEvent('cartUpdated', {
            detail: { cart, total: this.calculateTotal(cart) }
        }));
    }

    calculateTotal(cart) {
        return cart.reduce((total, item) => total + item.subtotal, 0);
    }
}
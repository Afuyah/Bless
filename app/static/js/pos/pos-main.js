// static/js/pos/pos-main.js
class POSSystem {
    constructor(shopId) {
        this.shopId = shopId;
        this.services = {
            product: new ProductService(shopId),
            cart: new CartService(shopId),
            checkout: new CheckoutService(shopId),
            socket: new SocketService(shopId)
        };
        
        this.init();
    }

    init() {
        this.loadInitialData();
        this.setupEventListeners();
        this.updateCartDisplay();
    }

    async loadInitialData() {
        try {
            const categories = await this.services.product.fetchCategories();
            if (categories.length > 0) {
                await this.loadProducts(categories[0].id);
            }
        } catch (error) {
            console.error('Initialization error:', error);
            this.showError('Failed to initialize POS system');
        }
    }

    async loadProducts(categoryId) {
        try {
            const products = await this.services.product.fetchProducts(categoryId);
            this.services.product.renderProducts(products, document.getElementById('products-container'));
            this.setupProductEvents();
        } catch (error) {
            console.error('Product load error:', error);
            this.showError('Failed to load products');
        }
    }

    setupEventListeners() {
        // Category selection
        document.querySelectorAll('.category-item').forEach(item => {
            item.addEventListener('click', () => {
                const categoryId = item.dataset.categoryId;
                this.loadProducts(categoryId);
            });
        });

        // Payment buttons
        document.querySelectorAll('.payment-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const paymentMethod = btn.dataset.method;
                this.processCheckout(paymentMethod);
            });
        });

        // Cart updates
        document.addEventListener('cartUpdated', (e) => {
            this.updateCartDisplay();
        });

        // Modal close
        document.querySelector('.close-modal').addEventListener('click', () => {
            document.getElementById('receipt-modal').style.display = 'none';
        });
    }

    setupProductEvents() {
        document.querySelectorAll('.product-card').forEach(card => {
            card.addEventListener('click', () => {
                if (card.classList.contains('out-of-stock')) return;
                
                const productId = card.dataset.productId;
                const product = {
                    id: productId,
                    name: card.querySelector('h3').textContent,
                    selling_price: this.parsePrice(card.querySelector('.price-info')),
                    combination_price: this.parseCombinationPrice(card),
                    combination_size: this.parseCombinationSize(card)
                };
                
                this.services.cart.addItem(product, 1);
            });
        });
    }

    parsePrice(priceElement) {
        const priceText = priceElement.textContent;
        const priceMatch = priceText.match(/Ksh (\d+\.\d{2})/);
        return priceMatch ? parseFloat(priceMatch[1]) : 0;
    }

    parseCombinationPrice(card) {
        const comboPriceElement = card.querySelector('.combination-price');
        if (!comboPriceElement) return null;
        const priceMatch = comboPriceElement.textContent.match(/Ksh (\d+\.\d{2})/);
        return priceMatch ? parseFloat(priceMatch[1]) : null;
    }

    parseCombinationSize(card) {
        const comboSizeElement = card.querySelector('.combination-price');
        if (!comboSizeElement) return null;
        const sizeMatch = comboSizeElement.textContent.match(/(\d+)/);
        return sizeMatch ? parseInt(sizeMatch[1]) : null;
    }

    updateCartDisplay() {
        const cart = this.services.cart.getCart();
        const total = this.services.cart.getTotal();
        
        // Update cart items
        const cartItemsEl = document.getElementById('cart-items');
        cartItemsEl.innerHTML = cart.map(item => this.createCartItemHTML(item)).join('');

        // Update totals
        document.getElementById('subtotal').textContent = `Ksh ${total.toFixed(2)}`;
        document.getElementById('total').textContent = `Ksh ${total.toFixed(2)}`;

        // Setup remove item buttons
        document.querySelectorAll('.remove-item').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const productId = btn.closest('.cart-item').dataset.productId;
                this.services.cart.removeItem(productId);
            });
        });
    }

    createCartItemHTML(item) {
        return `
            <div class="cart-item" data-product-id="${item.product_id}">
                <div class="item-info">
                    <h4>${item.product_name}</h4>
                    <div class="item-details">
                        <span>${item.quantity} × Ksh ${item.unit_price.toFixed(2)}</span>
                        <button class="remove-item">×</button>
                    </div>
                </div>
                <div class="item-subtotal">
                    Ksh ${item.subtotal.toFixed(2)}
                </div>
            </div>
        `;
    }

    async processCheckout(paymentMethod) {
        try {
            const result = await this.services.checkout.processCheckout(paymentMethod);
            this.showReceipt(result);
            this.services.cart.clearCart();
        } catch (error) {
            console.error('Checkout error:', error);
            this.showError(error.message || 'Checkout failed');
        }
    }

    showReceipt(saleData) {
        const modal = document.getElementById('receipt-modal');
        const content = document.getElementById('receipt-content');
        
        content.innerHTML = `
            <div class="receipt-header">
                <h3>Receipt #${saleData.sale_id}</h3>
                <p>${new Date().toLocaleString()}</p>
            </div>
            <div class="receipt-body">
                <p>Total: <strong>Ksh ${saleData.total.toFixed(2)}</strong></p>
                <p>Payment Method: ${saleData.payment_method.toUpperCase()}</p>
                <p>Profit: Ksh ${saleData.profit.toFixed(2)}</p>
            </div>
            <div class="receipt-footer">
                <p>Thank you for your purchase!</p>
            </div>
        `;
        
        modal.style.display = 'block';
    }

    showError(message) {
        this.services.socket.showNotification({
            type: 'error',
            message: message,
            duration: 5000
        });
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const shopId = document.body.dataset.shopId || {{ shop_id|tojson }};
    if (shopId) {
        new POSSystem(shopId);
    } else {
        console.error('Shop ID not found');
    }
});
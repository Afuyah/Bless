// static/js/pos/SocketService.js
class SocketService {
    constructor(shopId) {
        this.shopId = shopId;
        this.socket = io({
            reconnection: true,
            reconnectionAttempts: 5,
            reconnectionDelay: 1000
        });
        
        this.registerEventHandlers();
        this.setupConnectionMonitoring();
    }

    registerEventHandlers() {
        // Stock updates
        this.socket.on('stock_updated', (data) => {
            if (data.shop_id === this.shopId) {
                this.handleStockUpdate(data);
            }
        });

        // Low stock alerts
        this.socket.on('low_stock_alert', (data) => {
            if (data.shop_id === this.shopId) {
                this.showLowStockAlert(data);
            }
        });

        // Sale completions
        this.socket.on('sale_completed', (data) => {
            if (data.shop_id === this.shopId) {
                this.showSaleNotification(data);
            }
        });

        // Connection events
        this.socket.on('connect', () => {
            console.log('Connected to Socket.IO server');
            this.socket.emit('pos_connected', { shop_id: this.shopId });
        });

        this.socket.on('disconnect', () => {
            console.log('Disconnected from Socket.IO server');
        });
    }

    setupConnectionMonitoring() {
        setInterval(() => {
            if (!this.socket.connected) {
                console.log('Attempting to reconnect to Socket.IO server...');
            }
        }, 5000);
    }

    handleStockUpdate(data) {
        const productCards = document.querySelectorAll(`.product-card[data-product-id="${data.product_id}"]`);
        
        productCards.forEach(card => {
            const stockElement = card.querySelector('.stock-info');
            if (stockElement) {
                stockElement.textContent = `${data.stock} in stock`;
                stockElement.classList.toggle('low-stock', data.stock <= 5);
                
                // Disable card if out of stock
                card.classList.toggle('out-of-stock', data.stock <= 0);
                card.style.pointerEvents = data.stock <= 0 ? 'none' : 'auto';
            }
        });
    }

    showLowStockAlert(data) {
        this.showNotification({
            type: 'warning',
            message: `Low stock: ${data.product_name} (${data.stock} remaining)`,
            duration: 5000
        });
    }

    showSaleNotification(data) {
        this.showNotification({
            type: 'success',
            message: `Sale #${data.sale_id} completed (Ksh ${data.total.toFixed(2)})`,
            duration: 5000
        });
    }

    showNotification({ type, message, duration }) {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <span>${message}</span>
            <button class="close-notification">&times;</button>
        `;
        
        document.getElementById('notifications-container').appendChild(notification);
        
        notification.querySelector('.close-notification').addEventListener('click', () => {
            notification.remove();
        });
        
        if (duration) {
            setTimeout(() => notification.remove(), duration);
        }
    }

    requestStockUpdate(productId) {
        this.socket.emit('request_stock_update', {
            shop_id: this.shopId,
            product_id: productId
        });
    }
}
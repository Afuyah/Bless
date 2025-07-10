class ProductService {
    constructor(shopId) {
        this.shopId = shopId;
        this.baseUrl = `/shops/${shopId}/api`;
    }

    async fetchCategories() {
        try {
            const response = await fetch(`${this.baseUrl}/categories`);
            if (!response.ok) throw new Error('Failed to fetch categories');
            return await response.json();
        } catch (error) {
            console.error('Category fetch error:', error);
            throw error;
        }
    }

    async fetchProducts(categoryId) {
        try {
            const response = await fetch(`${this.baseUrl}/products/${categoryId}`);
            if (!response.ok) throw new Error('Failed to fetch products');
            return await response.json();
        } catch (error) {
            console.error('Product fetch error:', error);
            throw error;
        }
    }

    renderProducts(products, container) {
        container.innerHTML = products.map(product => `
            <div class="product-card" data-product-id="${product.id}">
                <h3>${product.name}</h3>
                <div class="price-info">
                    ${product.combination_price ? `
                        <span class="combination-price">
                            ${product.combination_size} for Ksh ${product.combination_price.toFixed(2)}
                        </span>
                        <span class="unit-price">
                            (Ksh ${product.combination_unit_price.toFixed(2)}/unit)
                        </span>
                    ` : `
                        <span class="single-price">
                            Ksh ${product.selling_price.toFixed(2)}
                        </span>
                    `}
                </div>
                <div class="stock-info ${product.stock <= 5 ? 'low-stock' : ''}">
                    ${product.stock} in stock
                </div>
            </div>
        `).join('');
    }
}
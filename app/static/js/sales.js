
// ============================== CART STATE ==============================

/**
 * Retrieve the shopping cart from localStorage, or return an empty array if
 * nothing’s stored (or if parsing fails).
 *
 * @returns {Array<Object>} The current cart items.
 */
function getCart() {
    const stored = localStorage.getItem('cart');
    if (!stored) return [];
    
    try {
      return JSON.parse(stored);
    } catch (err) {
      console.error('Failed to parse cart from localStorage:', err);
      return [];
    }
  }
  
  /**
   * Persist the shopping cart array to localStorage.
   *
   * @param {Array<Object>} cartItems
   */
  function saveCart(cartItems) {
    localStorage.setItem('cart', JSON.stringify(cartItems));
  }
  
  // Initialize cart once at load
  let cart = getCart();
  
  
  // ============================== UTILITIES ==============================
  
  /**
   * Format a number as a currency string with exactly two decimal places.
   *
   * @param {number|string} amount
   * @returns {string} e.g. "12.00"
   */
  function formatCurrency(amount) {
    const n = Number(amount);
    if (Number.isNaN(n)) {
      console.warn('formatCurrency received non‑numeric value:', amount);
      return '0.00';
    }
    return n.toFixed(2);
  }

  


  // ============================== PRODUCT DISPLAY ==============================

const productListEl = document.getElementById('product-list');
const noProductsEl = document.getElementById('no-products');

/**
 * Render an array of products into the DOM.
 *
 * @param {Array<Object>} products
 */
function populateProducts(products) {
  productListEl.innerHTML = '';

  if (products.length === 0) {
    noProductsEl.classList.remove('d-none');
    return;
  } else {
    noProductsEl.classList.add('d-none');
  }

  const fragment = document.createDocumentFragment();

  products.forEach(prod => {
    // Low‑stock badge
    const lowStockBadge = prod.stock < 5
      ? `<span class="text-danger ms-2">(${prod.stock})</span>`
      : '';

    // Combination pricing note
    const comboNote = prod.combination_size > 1
      ? `(<strong>${prod.combination_size}</strong> @ Ksh ${formatCurrency(prod.combination_price || 0)})`
      : '';

    // Build card
    const card = document.createElement('div');
    card.className = `product-item border border-primary rounded p-3 mb-3 ${prod.stock === 0 ? 'disabled-card' : 'clickable'}`;
    card.dataset.id = prod.id;
    card.dataset.name = prod.name;
    card.dataset.sellingPrice = formatCurrency(prod.selling_price || 0);
    card.dataset.combinationPrice = formatCurrency(prod.combination_price || 0);
    card.dataset.combinationUnitPrice = formatCurrency(prod.combination_unit_price || 0);
    card.dataset.stock = prod.stock;
    card.dataset.combinationSize = prod.combination_size || 1;

    card.innerHTML = `
      <h5 class="product-title mb-1">${prod.name}${lowStockBadge}</h5>
      <p class="product-price mb-1">Ksh ${formatCurrency(prod.selling_price || 0)} ${comboNote}</p>
      
    `;

    fragment.appendChild(card);
  });

  productListEl.appendChild(fragment);
}

/**
 * Display an error to the user. Defaults to toast, falls back to alert.
 *
 * @param {string} message
 */
function showError(message) {
  try {
    showToast(message, 'error');
  } catch {
    alert(message);
  }
}

/**
 * Fetch products for a category and render them.
 *
 * @param {number|string} categoryId
 */
async function fetchProducts(categoryId) {
  productListEl.innerHTML = '<p class="text-light">Loading products...</p>';
  noProductsEl.classList.add('d-none');

  try {
    const resp = await fetch(`/sales/api/products/${categoryId}`);
    if (!resp.ok) throw new Error(`Status ${resp.status}`);
    const data = await resp.json();

    if (Array.isArray(data.products)) {
      populateProducts(data.products);
    } else {
      populateProducts([]);
    }
  } catch (err) {
    console.error('fetchProducts failed:', err);
    showError('Failed to load products. Please try again.');
    populateProducts([]);
  }
}

// ============================== CATEGORY SELECTION ==============================

const categoryPanel    = document.getElementById('categoryPanel');
const categoryToggleBtn = document.getElementById('categoryToggleBtn');

// Delegate clicks on any .category-item or .panel-item
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.category-item, .panel-item');
  if (!btn) return;

  const categoryId = btn.dataset.category;

  // Highlight the selected category
  document
    .querySelectorAll('.category-item.active, .panel-item.active')
    .forEach(el => el.classList.remove('active'));
  btn.classList.add('active');

  // Close the mobile panel if it’s open
  categoryPanel.classList.remove('open');

  // Load the products
  fetchProducts(categoryId);
});

// Toggle the mobile category panel
if (categoryToggleBtn) {
  categoryToggleBtn.addEventListener('click', () => {
    categoryPanel.classList.toggle('open');
  });
}


// ============================== CART DISPLAY ==============================

const cartItemsEl   = document.getElementById('cart-items');
const totalAmountEl = document.getElementById('total-amount');
const logoutBtn     = document.getElementById('logout-button');

/**
 * Re‑renders the cart UI and recalculates the total.
 */
function updateCart() {
  // Clear existing items
  cartItemsEl.innerHTML = '';
  let total = 0;

  const fragment = document.createDocumentFragment();

  cart.forEach(item => {
    const comboSize      = item.combination_size || 1;
    const fullCombos     = Math.floor(item.quantity / comboSize);
    const remainderUnits = item.quantity % comboSize;

    // Calculate combination and remainder pricing
    let subtotal = fullCombos * item.combination_price;
    const remainderPrice = remainderUnits * item.selling_price;
    if (remainderUnits > 0) {
      subtotal += Math.min(remainderPrice, item.combination_price);
    }

    total += subtotal;

    // Build cart‑item element
    const itemEl = document.createElement('div');
    itemEl.className = 'cart-item d-flex justify-content-between align-items-center p-2 border-bottom';
    itemEl.innerHTML = `
      <span>${item.name} – Ksh ${formatCurrency(item.selling_price)} × ${item.quantity}</span>
      <span class="fw-bold text-primary">= Ksh ${formatCurrency(subtotal)}</span>
      <button class="btn btn-danger btn-sm remove-from-cart" data-id="${item.id}">&times;</button>
    `;
    fragment.appendChild(itemEl);
  });

  // Show “empty” message if needed
  if (cart.length === 0) {
    const emptyMsg = document.createElement('p');
    emptyMsg.className = 'text-muted text-center';
    emptyMsg.textContent = 'Your cart is empty.';
    fragment.appendChild(emptyMsg);
  }

  cartItemsEl.appendChild(fragment);
  totalAmountEl.textContent = formatCurrency(total);

  // Persist changes
  saveCart(cart);
}

// ============================== EVENT LISTENERS ==============================

/**
 * Delegate “remove” clicks on dynamically‑added buttons.
 */
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.remove-from-cart');
  if (!btn) return;

  const id    = btn.dataset.id;
  const index = cart.findIndex(item => String(item.id) === id);
  if (index > -1) {
    // Remove item & re-render
    cart.splice(index, 1);
    updateCart();
  }
});

/**
 * Handle logout: clear cart storage and redirect.
 */
if (logoutBtn) {
  logoutBtn.addEventListener('click', () => {
    localStorage.removeItem('cart');
    window.location.href = '/auth/logout';
  });
}

/**
 * On page load, initialize cart state and render.
 */
window.addEventListener('DOMContentLoaded', () => {
  cart = getCart();   // from earlier helper
  updateCart();
});






// Add item to cart on product click
$(document).on('click', '.product-item.clickable', function () {
    const productId = $(this).data('id');
    const productName = $(this).data('name');
    const productSellingPrice = parseFloat($(this).data('selling-price')) || 0;
    const productCombinationPrice = parseFloat($(this).data('combination-price')) || 0;
    const productCombinationUnitPrice = parseFloat($(this).data('combination-unit-price')) || 0;
    const productStock = parseInt($(this).data('stock')) || 0;
    const combinationSize = parseInt($(this).data('combination-size')) || 1;

    if (productStock === 0) {
        showError(`"${productName}" is currently out of stock.`);
        return;
    }

    let existingItem = cart.find(item => item.id === productId);

    if (existingItem) {
        if (existingItem.quantity < productStock) {
            existingItem.quantity += 1;
        } else {
            showError(`Cannot add more of "${productName}". Stock limit reached.`);
            return;
        }
    } else {
        cart.push({
            id: productId,
            name: productName,
            selling_price: productSellingPrice,
            combination_price: productCombinationPrice,
            combination_unit_price: productCombinationUnitPrice,
            quantity: 1,
            combination_size: combinationSize
        });
    }

    updateCart();
});

// Remove item from cart with animation
$(document).on('click', '.remove-from-cart', function () {
    const productId = $(this).data('id');
    const itemIndex = cart.findIndex(item => item.id === productId);

    if (itemIndex !== -1) {
        $(this).closest('.cart-item').fadeOut(300, function () {
            cart.splice(itemIndex, 1);
            updateCart();
        });
    }
});

// Clear cart button event
$(document).on('click', '#clear-cart', function () {
    if (cart.length === 0) {
        showError("Cart is already empty.");
        return;
    }

    if (confirm("Are you sure you want to clear the cart?")) {
        cart = [];
        localStorage.removeItem('cart');
        updateCart();
    }
});

// Function to save cart to localStorage
function saveCartToLocalStorage() {
    localStorage.setItem('cart', JSON.stringify(cart));
}

// Function to load cart from localStorage (ensuring persistence)
function loadCartFromLocalStorage() {
    const storedCart = localStorage.getItem('cart');
    if (storedCart) {
        cart = JSON.parse(storedCart);
    }
}

// Function to update cart display and calculate total
function updateCart() {
    $('#cart-items').empty();
    let total = 0;

    cart.forEach(item => {
        let subtotal = 0;
        const fullCombinations = Math.floor(item.quantity / item.combination_size);
        const remainingUnits = item.quantity % item.combination_size;
        
        subtotal += fullCombinations * item.combination_price;
        const individualRemainderPrice = remainingUnits * item.selling_price;
        
        if (remainingUnits > 0) {
            subtotal += Math.min(individualRemainderPrice, item.combination_price);
        }
        
        total += subtotal;

        $('#cart-items').append(`
            <div class="cart-item d-flex justify-content-between align-items-center p-2 border-bottom">
                <span>${item.name} - Ksh ${item.selling_price.toFixed(2)} x ${item.quantity}</span>
                <span class="fw-bold text-primary">= Ksh ${subtotal.toFixed(2)}</span>
                <button class="btn btn-danger btn-sm remove-from-cart" data-id="${item.id}">&times;</button>
            </div>
        `);
    });

    $('#total-amount').text(total.toFixed(2));

    if (cart.length === 0) {
        $('#cart-items').append('<p class="text-muted text-center">Your cart is empty.</p>');
    }

    saveCartToLocalStorage();
}

// Load cart from localStorage when the page loads
$(document).ready(function () {
    loadCartFromLocalStorage();
    updateCart();
});

// Function to show errors (replace alert with a better UI modal/toast)
function showError(message) {
    alert(message); // Can be replaced with a Bootstrap toast or modal
}



$(document).ready(function() {
    updateCart(); // Ensure cart UI is updated on page load
    $('#error-message').hide(); // Hide error message initially
});

// Handle payment method change
$('#payment-method').change(function () {
    const selectedMethod = $(this).val();
    const customerNameContainer = $('#customer-name-container');

    if (selectedMethod === 'credit') {
        customerNameContainer.slideDown(200); // Smoothly show input
    } else {
        customerNameContainer.slideUp(200); // Smoothly hide input
        $('#customer-name').val(''); // Clear input if not needed
    }
});

// Function to show error messages with animation
function showError(message) {
    const errorBox = $('#error-message');
    
    errorBox.text(message).fadeIn(300);
    
    setTimeout(() => {
        errorBox.fadeOut(300);
    }, 3000); // Auto-hide after 3 seconds
}

// Function to reset checkout form
function resetCheckoutForm() {
    $('#payment-method').val('').trigger('change'); // Reset and trigger change event
    $('#customer-name').val('');
    $('#error-message').fadeOut(300); // Hide error message
}






// Handle checkout
$('#checkout-btn').click(function () {
    if (cart.length === 0) {
        showError('Your cart is empty!');
        return;
    }

    // Populate the confirmation modal with cart items
    $('#checkout-items-list').empty(); // Clear previous items
    let total = 0;

    cart.forEach(item => {
        let subtotal = 0;
        const fullCombinations = Math.floor(item.quantity / item.combination_size);
        const remainingUnits = item.quantity % item.combination_size;

        subtotal += fullCombinations * item.combination_price;
        const individualRemainderPrice = remainingUnits * item.selling_price;
        const additionalCombinationPrice = item.combination_price;

        if (remainingUnits > 0) {
            subtotal += Math.min(individualRemainderPrice, additionalCombinationPrice);
        }

        total += subtotal;

        // Append item to the confirmation modal display
        $('#checkout-items-list').append(`
            <div class="checkout-item">
                ${item.name} - Ksh ${item.selling_price.toFixed(2)} x ${item.quantity} = Ksh ${subtotal.toFixed(2)}
            </div>
        `);
    });

    $('#checkout-total-amount').text(total.toFixed(2)); // Update the total amount display

    // Show the confirmation modal
    $('#checkoutConfirmationModal').modal('show');
});



// Confirm checkout button in modal
$(document).on('click', '#confirm-checkout-btn', function () {
    const checkoutButton = $('#checkout-btn');
    checkoutButton.prop('disabled', true); // Disable the original checkout button
    $('#checkout-loading').show(); // Show loading indicator

    const paymentMethod = $('#payment-method').val();
    const customerName = paymentMethod === 'credit' ? $('#customer-name').val().trim() : null;

    // Validate customer name if payment method is credit
    if (paymentMethod === 'credit' && !customerName) {
        showError('Please enter customer name for credit payments.');
        $('#customer-name').addClass('is-invalid'); // Highlight invalid input
        checkoutButton.prop('disabled', false); // Re-enable the checkout button
        $('#checkout-loading').hide(); // Hide loading indicator
        return;
    } else {
        $('#customer-name').removeClass('is-invalid'); // Remove highlight if valid
    }

    $.ajax({
        url: '/sales/checkout', // Adjust to your actual checkout endpoint
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ cart: cart, payment_method: paymentMethod, customer_name: customerName }),
        success: function () {
            $('#successModal').modal('show'); // Show success modal
            cart = []; // Clear cart
            updateCart(); // Update cart display
            resetCheckoutForm(); // Reset the form
        },
        error: function (xhr) {
            const errorMessage = xhr.responseJSON && xhr.responseJSON.message 
                ? xhr.responseJSON.message 
                : 'Checkout failed. Please try again.';
            showError(errorMessage);
        },
        complete: function () {
            checkoutButton.prop('disabled', false); // Re-enable the original checkout button
            $('#checkout-loading').hide(); // Hide loading indicator
            $('#checkoutConfirmationModal').modal('hide'); // Hide confirmation modal
        }
    });
});


// Function to reset the checkout form
function resetCheckoutForm() {
    $('#payment-method').val('mpesa'); // Set to default payment method
    $('#customer-name').val(''); // Clear customer name
    $('#customer-name-container').hide(); // Hide customer name input
}

// Debounce function to limit the frequency of search execution
function debounce(func, delay) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), delay);
    };
}

// Function to highlight matching text
function highlightMatch(text, searchTerm) {
    const regex = new RegExp(`(${searchTerm})`, 'gi');
    return text.replace(regex, '<span class="highlight">$1</span>'); // Wrap matches in a span for styling
}



// Search functionality for products and categories
const searchProductsAndCategories = debounce(function () {
    const searchTerm = $(this).val().toLowerCase();

    // Filter products
    $('.product-item').filter(function() {
        const productTitle = $(this).find('.product-title');
        const isVisible = productTitle.text().toLowerCase().includes(searchTerm);
        productTitle.html(isVisible ? highlightMatch(productTitle.text(), searchTerm) : productTitle.text()); // Highlight matches
        $(this).toggle(isVisible);
    });

    // Show or hide no products message
    $('#no-products').toggle($('#product-list').children(':visible').length === 0);

    // Filter categories
    $('.category-item').filter(function() {
        const isVisible = $(this).text().toLowerCase().includes(searchTerm);
        $(this).toggle(isVisible);
    });
}, 300); // Example delay of 300 ms for debouncing

// Event listener for search input
$('#search-input').on('input', searchProductsAndCategories);

// Function to highlight matched text in search results
function highlightMatch(text, term) {
    const escapedTerm = term.replace(/[-\/\\^$.*+?()[\]{}|]/g, '\\$&'); // Escape special regex characters
    const regex = new RegExp(`(${escapedTerm})`, 'gi'); // Case insensitive match
    return text.replace(regex, '<span class="highlight">$1</span>'); // Wrap matched text in a span for styling
}

// Attach the debounced search function to input event
$('#search').on('input', debounce(function() {
    const searchTerm = $(this).val();
    if (searchTerm.trim() !== '') { // Only highlight if the input is not empty
        searchProductsAndCategories.call(this);
    }
}, 300));

// Utility function to show error messages
function showError(message) {
    $('#error-message').text(message).show(); // Display error message
    $('#error-message').addClass('error-highlight'); // Add a class for styling
    setTimeout(() => {
        $('#error-message').removeClass('error-highlight'); // Remove class before hiding
        $('#error-message').hide(); // Hide after 5 seconds
    }, 5000); // Hide after 5 seconds
}


// Function to handle card animations and display adjustments
function animateCardsOnHover() {
    const productItems = document.querySelectorAll('.product-item');
    productItems.forEach(item => {
        item.addEventListener('mouseover', () => {
            item.style.transform = 'scale(1.02)';
        });
        item.addEventListener('mouseleave', () => {
            item.style.transform = 'scale(1)';
        });
    });
}

document.addEventListener('DOMContentLoaded', animateCardsOnHover);



document.addEventListener('DOMContentLoaded', () => {
    const panel    = document.getElementById('categoryPanel');
    const openBtn  = document.getElementById('catToggleBtn');
    const closeBtn = document.getElementById('catCloseBtn');
    const items    = document.querySelectorAll('#panelCategoryList .panel-item');
    const search   = document.getElementById('search');
  
    // Open panel
    openBtn.addEventListener('click', () => panel.classList.toggle('open'));
  
    // Close panel
    closeBtn.addEventListener('click', () => panel.classList.remove('open'));
  
    // Click category inside panel
    items.forEach(item => {
      item.addEventListener('click', () => {
        // Toggle active styles
        items.forEach(i => i.classList.remove('active'));
        item.classList.add('active');
  
        // Close panel
        panel.classList.remove('open');
  
        // Fetch products
        const catId = item.dataset.category;
        fetchProducts(catId, search ? search.value : '');
      });
    });
  
    // Close panel on outside click
    document.addEventListener('click', (e) => {
      if (panel.classList.contains('open')
          && !panel.contains(e.target)
          && e.target !== openBtn) {
        panel.classList.remove('open');
      }
    });
  });
  

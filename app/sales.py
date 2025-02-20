from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session
from flask_login import  current_user, login_required
from app.models import db, Product, Sale, CartItem, Category
from app import  socketio
from flask_socketio import emit
from collections import defaultdict
from sqlalchemy import func
from collections import Counter
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


sales_bp = Blueprint('sales', __name__)

# Helper function to check low stock
def check_low_stock(product):
    return product.stock < 5


@sales_bp.route('/sales')
@login_required
def sales_screen():
    categories = Category.query.all()  # Fetch all categories
    return render_template('sales/sales.html', categories=categories)


# Route for cashier to view sales screen
@sales_bp.route('/api/products/<int:category_id>', methods=['GET'])
@login_required
def get_products_by_category(category_id):
    try:
        # Fetch products by category, including all relevant fields
        products = Product.query.filter_by(category_id=category_id).all()  
        if not products:
            return jsonify({'message': 'No products found in this category'}), 404

        # Constructing the product list to include necessary fields
        product_list = [{
            'id': product.id,
            'name': product.name,
            'selling_price': float(product.selling_price) if product.selling_price is not None else None,  # Ensure it's a float
            'combination_price': float(product.combination_price) if product.combination_price is not None else None,  # Ensure it's a float
            'combination_unit_price': float(product.combination_unit_price) if product.combination_unit_price is not None else None,  # Ensure it's a float
            'combination_size': product.combination_size,
            'stock': product.stock
        } for product in products]

        return jsonify({'products': product_list})

    except Exception as e:
        logging.error(f"Error fetching products for category {category_id}: {e}")
        return jsonify({'error': 'An error occurred while fetching products.'}), 500


def calculate_subtotal(product, quantity):
    """Calculate the subtotal based on combination pricing logic."""
    full_combinations = quantity // product.combination_size
    remaining_units = quantity % product.combination_size
    subtotal = (full_combinations * product.combination_price) + (remaining_units * product.selling_price)
    return subtotal


@sales_bp.route('/add_to_cart', methods=['POST'])
@login_required
def add_to_cart():
    """Adds a product to the cart session, ensuring stock availability and correct pricing."""
    data = request.json
    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'Product not found'}), 404

    # Check stock availability
    if product.stock < quantity:
        return jsonify({'success': False, 'message': 'Insufficient stock'}), 400

    # Calculate subtotal
    subtotal = calculate_subtotal(product, quantity)

    # Initialize cart if not exists
    session.setdefault('cart', [])

    # Update or add product to cart
    cart = session['cart']
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += quantity
            item['subtotal'] = calculate_subtotal(product, item['quantity'])
            break
    else:
        cart.append({
            'product_id': product.id,
            'product_name': product.name,
            'quantity': quantity,
            'selling_price': product.selling_price,
            'combination_price': product.combination_price,
            'subtotal': subtotal
        })

    session.modified = True  # Ensure session updates persist

    return jsonify({'success': True, 'cart': session['cart']})


@sales_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    """Processes the checkout transaction, updates stock, and records the sale."""
    data = request.json
    cart = data.get('cart', [])
    payment_method = data.get('payment_method', 'cash')
    customer_name = data.get('customer_name')

    if not cart:
        return jsonify({'success': False, 'message': 'Cart is empty'}), 400

    total_amount = 0
    total_cost = 0  
    stock_updates = []
    cart_items = []

    try:
        for item in cart:
            product = Product.query.get(item['id'])  
            if not product:
                return jsonify({'success': False, 'message': f'Product {item["product_id"]} not found'}), 404

            quantity = item['quantity']

            # Check stock availability
            if product.stock < quantity:
                return jsonify({'success': False, 'message': f'Insufficient stock for {product.name}'}), 400

            # Calculate subtotal & cost
            subtotal = calculate_subtotal(product, quantity)
            total_amount += subtotal

            full_combinations = quantity // product.combination_size
            remaining_units = quantity % product.combination_size
            product_cost_price = product.cost_price if product.cost_price else 0

            total_cost += (full_combinations * product_cost_price * product.combination_size) + (remaining_units * product_cost_price)

            # Prepare stock updates
            stock_updates.append({'id': product.id, 'stock': product.stock - quantity})
            cart_items.append(CartItem(product_id=product.id, quantity=quantity, sale_id=None))  # Sale ID added after commit

        # Create Sale record
        sale = Sale(
            date=datetime.utcnow(),
            total=total_amount,
            payment_method=payment_method,
            customer_name=customer_name if payment_method == 'credit' else None,
            profit=total_amount - total_cost
        )
        db.session.add(sale)
        db.session.commit()  # Ensure sale ID is generated

        # Attach Sale ID to Cart Items
        for item in cart_items:
            item.sale_id = sale.id

        # Bulk update stock and save cart items
        db.session.bulk_update_mappings(Product, stock_updates)
        db.session.bulk_save_objects(cart_items)
        db.session.commit()

        # Emit stock update events
        for product_update in stock_updates:
            socketio.emit('stock_updated', product_update, broadcast=True)
            product = Product.query.get(product_update['id'])
            if check_low_stock(product):
                socketio.emit('low_stock_alert', {'product_name': product.name, 'stock': product.stock}, broadcast=True)

        return jsonify({'success': True, 'message': 'Sale completed successfully', 'profit': sale.profit})

    except IntegrityError as e:
        db.session.rollback()
        logging.error(f'Integrity error during checkout: {e}')
        return jsonify({'success': False, 'message': 'Database integrity error. Please try again.'}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f'Unexpected error during checkout: {e}')
        return jsonify({'success': False, 'message': 'An unexpected error occurred. Please contact support.'}), 500



@sales_bp.route('/api/todays-total-sales', methods=['GET'])
@login_required
def todays_total_sales():
    """Fetch today's total sales and number of transactions."""
    today = datetime.today().date()

    try:
        total_sales, total_transactions = db.session.query(
            func.coalesce(func.sum(Sale.total), 0),  # Ensure no NULL values
            func.count(Sale.id)
        ).filter(func.date(Sale.date) == today).first()

        return jsonify({
            'total_sales': round(total_sales, 2),
            'total_transactions': total_transactions
        })

    except SQLAlchemyError as e:
        logging.error(f"Error fetching today's sales: {e}")
        return jsonify({'error': 'Failed to fetch sales data'}), 500


@sales_bp.route('/reports/daily', methods=['GET'])
@login_required
def daily_sales_report():
    """Generates a daily sales report based on a provided date."""
    date_str = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))

    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
        return redirect(url_for('sales_bp.daily_sales_report'))

    # Query sales data for the selected date
    sales = Sale.query.filter(func.date(Sale.date) == report_date).all()
    
    if not sales:
        flash("No sales data available for the selected date.", "info")
        return render_template('daily_sales_report.html', 
                               sales=[], 
                               today=report_date, 
                               total_sales=0, 
                               total_transactions=0, 
                               daily_profit=0, 
                               mpesa_total=0, 
                               credit_total=0, 
                               most_sold_item=None, 
                               most_sold_quantity=0)

    # Calculate sales-related data
    total_sales = sum(sale.total for sale in sales)
    total_transactions = len(sales)
    daily_profit = sum(sale.profit for sale in sales)

    # Calculate totals based on payment methods
    payment_totals = {
        'mpesa': 0,
        'credit': 0
    }
    for sale in sales:
        payment_method = sale.payment_method.lower()
        if payment_method in payment_totals:
            payment_totals[payment_method] += sale.total

    # Determine the most sold item
    item_sales = Counter()
    for sale in sales:
        for item in sale.cart_items:
            item_sales[item.product.name] += item.quantity

    most_sold_item, most_sold_quantity = max(item_sales.items(), key=lambda x: x[1], default=(None, 0))

    return render_template('daily_sales_report.html', 
                           sales=sales, 
                           today=report_date, 
                           total_sales=round(total_sales, 2), 
                           total_transactions=total_transactions, 
                           daily_profit=round(daily_profit, 2), 
                           mpesa_total=round(payment_totals['mpesa'], 2),  
                           credit_total=round(payment_totals['credit'], 2),  
                           most_sold_item=most_sold_item, 
                           most_sold_quantity=most_sold_quantity)



@sales_bp.route('/reports/filter', methods=['GET'])
@login_required
def filter_sales_report():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not start_date_str or not end_date_str:
        flash("Please provide both start and end dates", "warning")
        return redirect(url_for('sales.daily_sales_report'))

    # Parse dates with error handling
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            flash("Start date must be before or equal to end date.", "warning")
            return redirect(url_for('sales.daily_sales_report'))
    except ValueError:
        flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
        return redirect(url_for('sales.daily_sales_report'))

    # Fetch sales within the specified date range
    sales = Sale.query.filter(Sale.date >= start_date, Sale.date <= end_date).all()

    if not sales:
        flash("No sales data available for the selected date range", "info")
        return render_template('filtered_sales_report.html', 
                               sales=[], 
                               total_sales=0, 
                               total_transactions=0, 
                               total_profit=0, 
                               avg_sale_value=0, 
                               unique_products=0, 
                               most_sold_item=None, 
                               most_sold_quantity=0,
                               mpesa_total=0,
                               credit_total=0)

    # Calculate total sales, transactions, and total profit
    total_sales = sum(sale.total for sale in sales)
    total_transactions = len(sales)
    total_profit = sum(sale.profit for sale in sales)

    # Track quantity sold for each item
    item_sales = Counter()
    for sale in sales:
        for item in sale.cart_items:
            item_sales[item.product.name] += item.quantity

    # Determine the most sold item based on quantities
    most_sold_item, most_sold_quantity = max(item_sales.items(), key=lambda x: x[1], default=(None, 0))

    # Calculate average sale value and unique products
    avg_sale_value = total_sales / total_transactions if total_transactions else 0
    unique_products = len(set(item.product.name for sale in sales for item in sale.cart_items))

    # Calculate totals based on payment methods
    mpesa_total = sum(sale.total for sale in sales if sale.payment_method.lower() == 'mpesa')
    credit_total = sum(sale.total for sale in sales if sale.payment_method.lower() == 'credit')

    return render_template('filtered_sales_report.html', 
                           sales=sales, 
                           total_sales=round(total_sales, 2), 
                           total_transactions=total_transactions, 
                           total_profit=round(total_profit, 2), 
                           avg_sale_value=round(avg_sale_value, 2), 
                           unique_products=unique_products, 
                           most_sold_item=most_sold_item, 
                           most_sold_quantity=most_sold_quantity,
                           mpesa_total=round(mpesa_total, 2),  # Include M-Pesa total
                           credit_total=round(credit_total, 2))  # Include credit total

@sales_bp.route('/reports/monthly', methods=['GET'])
@login_required
def monthly_sales_report():
    month_str = request.args.get('month', datetime.today().strftime('%Y-%m'))
    try:
        report_month = datetime.strptime(month_str, '%Y-%m').date()
    except ValueError:
        flash("Invalid month format. Please use YYYY-MM.", "danger")
        return redirect(url_for('sales_bp.monthly_sales_report'))

    # Fetch sales for the specified month
    sales = Sale.query.filter(func.extract('year', Sale.date) == report_month.year,
                               func.extract('month', Sale.date) == report_month.month).all()

    # Calculate total sales, transactions, and profit
    total_sales = sum(sale.total for sale in sales)
    total_transactions = len(sales)
    total_profit = sum(sale.profit for sale in sales)

    # Render the report template with calculated values and the datetime module
    return render_template('monthly_sales_report.html', 
                           sales=sales, 
                           total_sales=round(total_sales, 2), 
                           total_transactions=total_transactions, 
                           total_profit=round(total_profit, 2),
                           datetime=datetime) 

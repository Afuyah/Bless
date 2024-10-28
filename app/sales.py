from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import  current_user, login_required
from app.models import db, Product, Sale, CartItem, Category
from app import  socketio
from flask_socketio import emit
from collections import defaultdict
from sqlalchemy import func


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
    return render_template('sales.html', categories=categories)


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
            'selling_price': product.selling_price,
            'combination_price': product.combination_price,
            'combination_unit_price': product.combination_unit_price,
            'combination_size': product.combination_size,
            'stock': product.stock
        } for product in products]

        return jsonify({'products': product_list})

    except Exception as e:
        logging.error(f"Error fetching products for category {category_id}: {e}")
        return jsonify({'error': 'An error occurred while fetching products.'}), 500


@sales_bp.route('/add_to_cart', methods=['POST'])
@login_required
def add_to_cart():
    data = request.json
    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)  # Default to 1 if not provided

    product = Product.query.get(product_id)
    if not product:
        return jsonify({'success': False, 'message': 'Product not found'}), 404

    # Check stock availability
    if product.stock < quantity:
        return jsonify({'success': False, 'message': 'Insufficient stock'}), 400

    # Determine the subtotal based on quantity
    subtotal = 0
    if quantity < product.combination_size:
        # Use selling price for a single item or quantities below combination size
        subtotal = product.selling_price * quantity
    else:
        # Use combination price for multiples of the combination size
        subtotal = (quantity // product.combination_size) * product.combination_price
        if quantity % product.combination_size != 0:
            subtotal += (quantity % product.combination_size) * product.selling_price  # Add the remainder at selling price

    return jsonify({
        'success': True,
        'product_id': product.id,
        'product_name': product.name,
        'quantity': quantity,
        'selling_price': product.selling_price,
        'combination_price': product.combination_price,
        'subtotal': subtotal  # Return calculated subtotal
    })
@sales_bp.route('/checkout', methods=['POST'])
@login_required
def checkout():
    data = request.json
    cart = data.get('cart', [])
    payment_method = data.get('payment_method', 'cash')
    customer_name = data.get('customer_name')

    if not cart:
        return jsonify({'success': False, 'message': 'Cart is empty'}), 400

    total_amount = 0
    items_to_update_stock = []

    for item in cart:
        product = Product.query.get(item['id'])  # Ensure you're using the correct key for product ID
        if product is None:
            return jsonify({'success': False, 'message': 'Product not found'}), 404

        quantity = item['quantity']

        # Check stock availability before any calculations
        if product.stock < quantity:
            return jsonify({'success': False, 'message': f'Insufficient stock for {product.name}'}), 400

        # Calculate subtotal using combination-first approach
        full_combinations = quantity // product.combination_size
        remaining_units = quantity % product.combination_size

        # Calculate cost for full combinations
        subtotal = full_combinations * product.combination_price

        # Calculate cost for remaining units and choose the cheaper option
        individual_remainder_cost = remaining_units * product.selling_price
        additional_combination_cost = product.combination_price  # Cost of an extra combination

        # Add the cheaper of the two options for the remaining units
        subtotal += min(individual_remainder_cost, additional_combination_cost)

        total_amount += subtotal
        items_to_update_stock.append((product, quantity))

    # Create the Sale object
    sale = Sale(
        date=datetime.utcnow(),
        total=total_amount,
        payment_method=payment_method,
        customer_name=customer_name if payment_method == 'credit' else None
    )
    db.session.add(sale)

    try:
        # Commit the sale to get a valid sale_id
        db.session.commit()

        # Update stock and create CartItem records
        for product, quantity in items_to_update_stock:
            product.stock -= quantity
            cart_item = CartItem(product_id=product.id, quantity=quantity, sale_id=sale.id)
            db.session.add(cart_item)

        db.session.commit()

        # Emit real-time updates after successful commit
        for product, quantity in items_to_update_stock:
            socketio.emit('stock_updated', {'id': product.id, 'name': product.name, 'stock': product.stock}, broadcast=True)
            if check_low_stock(product):  # Check for low stock
                socketio.emit('low_stock_alert', {'product_name': product.name, 'stock': product.stock}, broadcast=True)

        return jsonify({'success': True, 'message': 'Sale completed successfully'})
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f'Integrity error during transaction: {e}')
        return jsonify({'success': False, 'message': 'Integrity error during transaction'}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f'Error during transaction: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@sales_bp.route('/reports/daily', methods=['GET'])
@login_required
def daily_sales_report():
    # Get the date from request arguments, defaulting to today
    date_str = request.args.get('date', datetime.today().date().strftime('%Y-%m-%d'))
    report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    # Fetch sales for the specified date
    sales = Sale.query.filter(func.date(Sale.date) == report_date).all()

    # If no sales are found for the date, flash a message and exit
    if not sales:
        flash("No sales data available for the selected date", "info")
        return render_template('daily_sales_report.html', 
                               sales=[], 
                               today=report_date, 
                               total_sales=0, 
                               total_transactions=0, 
                               daily_profit=0, 
                               most_sold_item=None, 
                               most_sold_quantity=0)

    # Initialize values for total sales and transactions count
    total_sales = sum(sale.total for sale in sales)
    total_transactions = len(sales)

    # Initialize tracking for daily profit and most sold item details
    daily_profit = 0
    item_sales = {}

    # Calculate profit per sale and add to daily profit
    for sale in sales:
        sale_profit = 0
        for item in sale.cart_items:
            product = item.product
            quantity = item.quantity

            # Calculate profit per item based on combination/unit pricing
            if product.combination_size and quantity >= product.combination_size:
                profit_per_unit = product.combination_unit_price - product.cost_price
            else:
                profit_per_unit = product.selling_price - product.cost_price

            # Total profit for this item in this sale
            item_profit = profit_per_unit * quantity
            sale_profit += item_profit

            # Track quantity sold for the most-sold item
            if product.name in item_sales:
                item_sales[product.name] += quantity
            else:
                item_sales[product.name] = quantity

        # Add the sale's profit to the daily profit
        daily_profit += sale_profit

    # Determine the most sold item based on quantities
    most_sold_item, most_sold_quantity = max(item_sales.items(), key=lambda x: x[1], default=(None, 0))

    # Format the total sales and daily profit to two decimal places
    total_sales = round(total_sales, 2)
    daily_profit = round(daily_profit, 2)

    # Render the report template with calculated values
    return render_template('daily_sales_report.html', 
                           sales=sales, 
                           today=report_date, 
                           total_sales=total_sales, 
                           total_transactions=total_transactions, 
                           daily_profit=daily_profit, 
                           most_sold_item=most_sold_item, 
                           most_sold_quantity=most_sold_quantity)



@sales_bp.route('/reports/filter', methods=['GET'])
@login_required
def filter_sales_report():
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if not start_date_str or not end_date_str:
        flash("Please provide both start and end dates", "warning")
        return redirect(url_for('sales_bp.daily_sales_report'))

    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

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
                               most_sold_quantity=0)

    total_sales = sum(sale.total for sale in sales)
    total_transactions = len(sales)
    total_profit = 0
    item_sales = {}

    for sale in sales:
        sale_profit = 0
        for item in sale.cart_items:
            product = item.product
            quantity = item.quantity

            if product.combination_size and quantity >= product.combination_size:
                profit_per_unit = product.combination_unit_price - product.cost_price
            else:
                profit_per_unit = product.selling_price - product.cost_price

            item_profit = profit_per_unit * quantity
            sale_profit += item_profit

            if product.name in item_sales:
                item_sales[product.name] += quantity
            else:
                item_sales[product.name] = quantity

        total_profit += sale_profit

    most_sold_item, most_sold_quantity = max(item_sales.items(), key=lambda x: x[1], default=(None, 0))

    # Calculate average sale value and unique products
    avg_sale_value = total_sales / total_transactions if total_transactions else 0
    unique_products = len(set(item.product.name for sale in sales for item in sale.cart_items))

    return render_template('filtered_sales_report.html', 
                           sales=sales, 
                           total_sales=round(total_sales, 2), 
                           total_transactions=total_transactions, 
                           total_profit=round(total_profit, 2), 
                           avg_sale_value=round(avg_sale_value, 2), 
                           unique_products=unique_products, 
                           most_sold_item=most_sold_item, 
                           most_sold_quantity=most_sold_quantity)

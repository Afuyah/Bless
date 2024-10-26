from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.models import db, Product, Sale, CartItem, Category
from app import socketio
from flask_socketio import emit
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
import logging
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

        # Constructing the product list to include all necessary fields
        product_list = [{
            'id': product.id,
            'name': product.name,
            'selling_price': product.selling_price,
            'combination_price': product.combination_price,
            'combination_unit_price': product.combination_unit_price,
            'combination_size': product.combination_size,
            'stock': product.stock,
            'is_weight_based': product.unit_type == 'weight',  # Assuming 'weight' indicates a weight-based product
            'unit_type': str(product.unit_type)  # Convert to string for JSON serialization
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
    today = datetime.today().date()  # Get today's date
    sales = Sale.query.filter(db.func.date(Sale.date) == today).all()

    if not sales:
        flash("No sales data available for today", "info")

    return render_template('daily_sales_report.html', sales=sales, today=today)

# Weekly sales report
@sales_bp.route('/reports/weekly', methods=['GET'])
@login_required
def weekly_sales_report():
    one_week_ago = datetime.utcnow().date() - timedelta(days=7)
    sales = Sale.query.filter(Sale.date >= one_week_ago).all()
    return render_template('weekly_sales_report.html', sales=sales)

@sales_bp.route('/reports/filter', methods=['POST'])
@login_required
def filter_sales_report():
    start_date_str = request.json.get('start_date')
    end_date_str = request.json.get('end_date')

    # Parse the dates from the request
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

    # Use join to optimize querying sales with items
    sales = Sale.query.filter(Sale.date.between(start_date, end_date)).all()

    # Initialize report data and totals
    report_data = {}
    total_revenue = 0
    total_items_sold = 0
    total_profit = 0

    # Process sales data to gather required information
    for sale in sales:
        sale_items = sale.cart_items  # Get all items in the sale
        total_sale_value = sale.total  # Total revenue for this sale

        for item in sale_items:
            product_name = item.product.name  # Get the product name
            quantity = item.quantity
            unit_price = item.product.price  # Cost price of the product
            cost_price = unit_price * quantity
            profit = total_sale_value - cost_price

            # Group by product name instead of category
            if product_name not in report_data:
                report_data[product_name] = {
                    'total_sold': 0,
                    'total_revenue': 0,
                    'cost_price': 0,
                    'profit': 0,
                }

            # Accumulate the values for each product
            report_data[product_name]['total_sold'] += quantity
            report_data[product_name]['total_revenue'] += total_sale_value
            report_data[product_name]['cost_price'] += cost_price
            report_data[product_name]['profit'] += profit

            # Aggregate totals
            total_revenue += total_sale_value
            total_items_sold += quantity
            total_profit += profit

    # Convert the report data into a list for the JSON response
    report_data_list = [
        {
            'product_name': product,
            'total_sold': data['total_sold'],
            'total_revenue': data['total_revenue'],
            'cost_price': data['cost_price'],
            'profit': data['profit'],
        }
        for product, data in report_data.items()
    ]

    # Return the sales data and aggregated totals in JSON format
    return jsonify({
        'sales': report_data_list,
        'total_revenue': total_revenue,
        'total_items_sold': total_items_sold,
        'total_profit': total_profit
    })




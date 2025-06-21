from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session,current_app
from flask_login import  current_user, login_required
from app.models import db, Product, Sale, CartItem, Category
from app import  socketio, cache
from flask_socketio import emit
from collections import defaultdict
from sqlalchemy import func
from decimal import Decimal
from collections import Counter
from sqlalchemy.orm import joinedload
from werkzeug.exceptions import BadRequest
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from collections import defaultdict, OrderedDict
from flask import request, render_template, current_app, flash, redirect, url_for, jsonify
from sqlalchemy import func, extract
from sqlalchemy.orm import joinedload
from app.utils.render import render_htmx

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
    
    categories = cache.get('categories')
    if not categories:
        categories = Category.query.all()
        cache.set('categories', categories, timeout=60)

    products = Product.query.all()  # Ensure this is included
    return render_template('sales/pos.html', categories=categories, products=products)


# Route for cashier to view sales screen
@sales_bp.route('/api/products/<int:category_id>', methods=['GET'])
@login_required
def get_products_by_category(category_id):
    try:
        cache_key = f'products_{category_id}'
        products = cache.get(cache_key)

        if not products:
            products = Product.query.filter_by(category_id=category_id).all()

            if not products:
                return jsonify({'message': 'No products found in this category'}), 404

            # Convert product data to JSON-friendly format before caching
            products = [{
                'id': product.id,
                'name': product.name,
                'selling_price': float(product.selling_price) if product.selling_price is not None else None,
                'combination_price': float(product.combination_price) if product.combination_price is not None else None,
                'combination_unit_price': float(product.combination_unit_price) if product.combination_unit_price is not None else None,
                'combination_size': product.combination_size,
                'stock': product.stock
            } for product in products]

            cache.set(cache_key, products, timeout=300)  # Cache for 5 minutes

        return jsonify({'products': products})

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

    # Calculate subtotal based on quantity
    subtotal = 0
    if quantity < product.combination_size:
        subtotal = product.selling_price * quantity
    else:
        subtotal = (quantity // product.combination_size) * product.combination_price
        if quantity % product.combination_size != 0:
            subtotal += (quantity % product.combination_size) * product.selling_price

    # Initialize the cart in session if it doesn't exist
    if 'cart' not in session:
        session['cart'] = []

    # Add or update the item in the session cart
    cart = session['cart']
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += quantity
            item['subtotal'] += subtotal
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

    session['cart'] = cart  # Update session cart
    return jsonify({'success': True, 'cart': session['cart']})

    
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
    total_cost = 0  # Initialize total cost for profit calculation
    items_to_update_stock = []

    for item in cart:
        product = Product.query.get(item['id'])
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

        # Calculate the total cost for profit calculation
        total_cost += (full_combinations * product.cost_price * product.combination_size) + (remaining_units * product.cost_price)

        items_to_update_stock.append((product, quantity))

    # Create the Sale object with profit calculation
    sale = Sale(
        date=datetime.utcnow(),
        total=total_amount,
        payment_method=payment_method,
        customer_name=customer_name if payment_method == 'credit' else None,
    )
    
    # Calculate profit
    sale_profit = total_amount - total_cost  # Profit = Total Sales - Total Cost
    sale.profit = sale_profit  # Set the profit calculated for this sale
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

        return jsonify({'success': True, 'message': 'Sale completed successfully', 'profit': sale_profit})
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f'Integrity error during transaction: {e}')
        return jsonify({'success': False, 'message': 'Integrity error during transaction'}), 400
    except Exception as e:
        db.session.rollback()
        logging.error(f'Error during transaction: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


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
    try:
        date_str = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        if report_date > datetime.today().date():
            raise ValueError("Future dates not allowed")
        if report_date < (datetime.today() - timedelta(days=730)).date():
            raise ValueError("Date too far in the past")

    except ValueError as e:
        if request.headers.get('HX-Request'):
            return render_template('sales/fragments/_error_message.html', message=str(e)), 400
        if request.accept_mimetypes.accept_json:
            return jsonify({"error": str(e)}), 400
        flash(str(e), "danger")
        return redirect(url_for('sales_bp.daily_sales_report'))

    cache_key = f"daily_report_{report_date}"
    if request.headers.get("HX-Request"):
        cached = cache.get(cache_key)
        if cached:
            return cached

    report_data = generate_daily_report_data(report_date)

    # ✅ JSON for APIs (serialized safely)
    if request.accept_mimetypes.best == 'application/json':
        serialized = {
            **report_data,
            'sales': [
                {
                    "id": sale.id,
                    "user": sale.user.username if sale.user else None,
                    "total": float(sale.total),
                    "profit": float(sale.profit or 0),
                    "payment_method": sale.payment_method,
                    "date": sale.date.strftime('%Y-%m-%d %H:%M:%S'),
                    "items": [
                        {
                            "product": item.product.name,
                            "quantity": item.quantity,
                            "total_price": float(item.total_price)
                        }
                        for item in sale.cart_items
                    ]
                }
                for sale in report_data.get("sales", [])
            ]
        }
        return jsonify(serialized)

    #  HTMX fragment or full wrapper via render_htmx()
    return render_htmx(
        "reports/fragments/_daily_report.html",
        timedelta=timedelta,
        datetime=datetime,
        **report_data
    )



def generate_daily_report_data(report_date):
    try:
        # Initialize all data structures
        product_sales = defaultdict(lambda: {'quantity': 0, 'revenue': Decimal('0.0')})
        payment_methods = defaultdict(Decimal)
        hourly_sales = defaultdict(Decimal)
        staff_performance = defaultdict(lambda: {'sales': 0, 'amount': Decimal('0.0')})
        complete_product_sales = defaultdict(lambda: {'quantity': 0, 'revenue': Decimal('0.0')})

        # Base sales query with eager loading - MUST COME FIRST
        sales = Sale.query.filter(func.date(Sale.date) == report_date).options(
            joinedload(Sale.cart_items).joinedload(CartItem.product),
            joinedload(Sale.user)
        ).all()

        if not sales:
            return {
                'sales': [],
                'report_date': report_date,
                'summary': {
                    'total_sales': 0.0,
                    'total_transactions': 0,
                    'total_profit': 0.0,
                    'avg_sale': 0.0
                },
                'payment_methods': {},
                'product_performance': [],
                'hourly_trends': [],
                'staff_performance': [],
                'complete_products': []
            }

        # Process all sales data
        for sale in sales:
            # Payment methods
            method = sale.payment_method.lower()
            payment_methods[method] += Decimal(str(sale.total))

            # Hourly trends
            hour = sale.date.hour
            hourly_sales[f"{hour}:00-{hour+1}:00"] += Decimal(str(sale.total))

            # Staff performance
            if sale.user:
                staff_performance[sale.user.username]['sales'] += 1
                staff_performance[sale.user.username]['amount'] += Decimal(str(sale.total))

            # Product performance (both top and complete)
            for item in sale.cart_items:
                product_name = item.product.name
                quantity = item.quantity
                revenue = Decimal(str(item.total_price))

                complete_product_sales[product_name]['quantity'] += quantity
                complete_product_sales[product_name]['revenue'] += revenue
                product_sales[product_name]['quantity'] += quantity
                product_sales[product_name]['revenue'] += revenue

        # Calculate summary statistics
        total_sales = sum(Decimal(str(sale.total)) for sale in sales)
        total_transactions = len(sales)
        total_profit = sum(Decimal(str(sale.profit)) if sale.profit is not None else Decimal('0') for sale in sales)
        avg_sale = total_sales / Decimal(str(total_transactions)) if total_transactions else Decimal('0')

        # Prepare sorted product lists
        sorted_products = sorted(
            [(name, {'quantity': data['quantity'], 'revenue': float(data['revenue'])}) 
             for name, data in product_sales.items()],
            key=lambda x: x[1]['revenue'],
            reverse=True
        )[:10]

        complete_products_list = sorted(
            [(name, {'quantity': data['quantity'], 'revenue': float(data['revenue'])}) 
             for name, data in complete_product_sales.items()],
            key=lambda x: x[1]['revenue'],
            reverse=True
        )

        return {
            'sales': sales,
            'report_date': report_date,
            'summary': {
                'total_sales': float(total_sales),
                'total_transactions': total_transactions,
                'total_profit': float(total_profit),
                'avg_sale': float(avg_sale)
            },
            'payment_methods': {k: float(v) for k, v in payment_methods.items()},
            'product_performance': sorted_products,
            'hourly_trends': [(k, float(v)) for k, v in sorted(hourly_sales.items())],
            'complete_products': complete_products_list,
            'staff_performance': sorted(
                [(k, {'sales': v['sales'], 'amount': float(v['amount'])}) 
                 for k, v in staff_performance.items()],
                key=lambda x: x[1]['amount'],
                reverse=True
            )
        }

    except Exception as e:
        current_app.logger.error(f"Error generating daily report: {str(e)}")
        return {
            'error': str(e),
            'sales': [],
            'report_date': report_date,
            'summary': {
                'total_sales': 0.0,
                'total_transactions': 0,
                'total_profit': 0.0,
                'avg_sale': 0.0
            },
            'payment_methods': {},
            'product_performance': [],
            'hourly_trends': [],
            'staff_performance': [],
            'complete_products': []
        }



@sales_bp.route('/weekly-sales-report')
@login_required
def weekly_sales_report():
    try:
        week = request.args.get('week', datetime.today().strftime('%Y-W%W'))
        year, week_num = map(int, week.split('-W'))
        start_date = datetime.strptime(f'{year}-W{week_num}-1', "%Y-W%W-%w").date()
        end_date = start_date + timedelta(days=6)
    except ValueError:
        today = datetime.today().date()
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
        week = start_date.strftime('%Y-W%W')

    context = generate_weekly_report_context(week, start_date, end_date)

    if request.headers.get("HX-Request"):
        return render_template("reports/fragments/_weekly_sales_fragment.html", **context)

    return render_htmx(
    "reports/fragments/_weekly_sales_fragment.html",
    **context
)


def generate_weekly_report_context(week, start_date, end_date):
    sales = Sale.query.filter(
        Sale.date >= start_date,
        Sale.date <= end_date
    ).options(
        joinedload(Sale.cart_items).joinedload(CartItem.product),
        joinedload(Sale.user)
    ).order_by(Sale.date.desc()).all()

    total_sales = float(sum(Decimal(str(sale.total)) for sale in sales)) if sales else 0.0
    total_profit = float(sum(Decimal(str(sale.profit or 0)) for sale in sales)) if sales else 0.0
    total_transactions = len(sales)
    avg_sale = float(total_sales / total_transactions) if total_transactions else 0.0

    prev_week_start = start_date - timedelta(weeks=1)
    prev_week_end = end_date - timedelta(weeks=1)
    prev_week_sales = float(
        db.session.query(func.sum(Sale.total))
        .filter(Sale.date >= prev_week_start, Sale.date <= prev_week_end)
        .scalar() or 0.0
    )
    wow_change = float(((total_sales - prev_week_sales) / prev_week_sales * 100)) if prev_week_sales else 0.0

    calendar = {
        'prev_week': (start_date - timedelta(weeks=1)).strftime('%Y-W%W'),
        'next_week': (start_date + timedelta(weeks=1)).strftime('%Y-W%W'),
        'current_week': datetime.today().strftime('%Y-W%W')
    }

    weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    daily_data = {day: {'sales': 0.0, 'transactions': 0} for day in weekdays}
    for sale in sales:
        day = sale.date.strftime('%A')
        daily_data[day]['sales'] += float(sale.total)
        daily_data[day]['transactions'] += 1

    hourly_sales = {f"{hour:02d}:00": 0.0 for hour in range(24)}
    for sale in sales:
        hour_key = sale.date.strftime('%H:00')
        hourly_sales[hour_key] += float(sale.total)
    hourly_labels = sorted(hourly_sales.keys())
    hourly_values = [hourly_sales[hour] for hour in hourly_labels]

    payment_methods = defaultdict(float)
    for sale in sales:
        method = sale.payment_method.lower()
        payment_methods[method] += float(sale.total)

    product_sales = defaultdict(lambda: {'quantity': 0, 'revenue': Decimal('0')})
    for sale in sales:
        for item in sale.cart_items:
            product_sales[item.product.name]['quantity'] += item.quantity
            product_sales[item.product.name]['revenue'] += Decimal(str(item.total_price))

    sorted_products = sorted(
        [(k, {'quantity': v['quantity'], 'revenue': float(v['revenue'])})
         for k, v in product_sales.items()],
        key=lambda x: x[1]['revenue'],
        reverse=True
    )[:10]

    return {
        'sales': sales,
        'week': week,
        'date_range': f"{start_date.strftime('%b %d, %Y')} - {end_date.strftime('%b %d, %Y')}",
        'total_sales': total_sales,
        'total_profit': total_profit,
        'total_transactions': total_transactions,
        'avg_sale': avg_sale,
        'prev_week_sales': prev_week_sales,
        'wow_change': wow_change,
        'calendar': calendar,
        'daily_data': daily_data,
        'hourly_labels': hourly_labels,
        'hourly_values': hourly_values,
        'payment_methods': dict(payment_methods),
        'product_performance': sorted_products
    }




class MonthlySalesAnalyzer:
    """Helper class to encapsulate monthly sales analytics logic"""
    
    def __init__(self, month_str=None):
        self.month_str = month_str or datetime.utcnow().strftime('%Y-%m')
        self.report_month = None
        self.first_day = None
        self.last_day = None
        self.prev_month = None
        self.next_month = None
        self.days_in_month = None
        self.sales = []
        
    def initialize_dates(self):
        """Initialize and validate date ranges"""
        try:
            self.report_month = datetime.strptime(self.month_str, '%Y-%m').date()
            self.first_day = self.report_month.replace(day=1)
            self.last_day = (self.first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            self.prev_month = (self.first_day - timedelta(days=1)).replace(day=1)
            self.next_month = (self.first_day + timedelta(days=32)).replace(day=1)
            self.days_in_month = self.last_day.day
            return True
        except ValueError as e:
            current_app.logger.error(f"Date initialization error: {str(e)}")
            return False
    
    def fetch_sales_data(self):
        """Query sales data with eager loading"""
        try:
            self.sales = (
                Sale.query.filter(
                    Sale.date >= self.first_day,
                    Sale.date <= self.last_day
                )
                .options(
                    joinedload(Sale.cart_items).joinedload(CartItem.product),
                    joinedload(Sale.user)
                )
                .order_by(Sale.date)
                .all()
            )
            return True
        except Exception as e:
            current_app.logger.error(f"Sales query error: {str(e)}")
            return False
    
    def calculate_core_metrics(self):
        """Calculate key performance metrics with precise decimal calculations"""
        metrics = {
            'total_sales': Decimal('0.0'),
            'total_profit': Decimal('0.0'),
            'total_transactions': len(self.sales),
            'avg_sale': Decimal('0.0'),
            'avg_profit_margin': Decimal('0.0'),
            'products_sold': 0,
            'refund_rate': Decimal('0.0'),
            'total_cost': Decimal('0.0')
        }

        if not self.sales:
            return {k: float(v) if isinstance(v, Decimal) else v for k, v in metrics.items()}

        refund_count = 0
        total_cost = Decimal('0.0')
        
        for sale in self.sales:
            sale_total = Decimal(str(sale.total))
            metrics['total_sales'] += sale_total
            metrics['total_profit'] += Decimal(str(sale.profit)) if sale.profit else Decimal('0.0')
            
            if hasattr(sale, 'is_refund') and sale.is_refund:
                refund_count += 1
            
            for item in sale.cart_items:
                metrics['products_sold'] += item.quantity
                if item.product and item.product.cost_price:
                    item_cost = Decimal(str(item.product.cost_price)) * item.quantity
                    total_cost += item_cost

        # Calculate derived metrics
        metrics['total_cost'] = total_cost
        metrics['avg_sale'] = metrics['total_sales'] / metrics['total_transactions'] if metrics['total_transactions'] > 0 else Decimal('0.0')
        metrics['refund_rate'] = (Decimal(refund_count) / metrics['total_transactions'] * 100) if metrics['total_transactions'] > 0 else Decimal('0.0')
        
        if metrics['total_sales'] > 0:
            gross_profit = metrics['total_sales'] - total_cost
            metrics['avg_profit_margin'] = (gross_profit / metrics['total_sales'] * 100)
        else:
            metrics['avg_profit_margin'] = Decimal('0.0')

        # Convert all Decimal values to float for JSON serialization
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in metrics.items()}
    
    def calculate_comparisons(self):
        """Calculate month-over-month and year-over-year comparisons with precise calculations"""
        comparisons = {
            'mom_sales': Decimal('0.0'),
            'mom_change': Decimal('0.0'),
            'yoy_sales': Decimal('0.0'),
            'yoy_change': Decimal('0.0'),
            'mom_profit': Decimal('0.0'),
            'yoy_profit': Decimal('0.0')
        }

        # Month-over-month comparison
        prev_month_last_day = (self.prev_month.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        prev_month_data = db.session.query(
            func.sum(Sale.total).label('total_sales'),
            func.sum(Sale.profit).label('total_profit')
        ).filter(
            Sale.date >= self.prev_month,
            Sale.date <= prev_month_last_day
        ).first()
        
        prev_month_sales = Decimal(str(prev_month_data.total_sales)) if prev_month_data.total_sales else Decimal('0.0')
        prev_month_profit = Decimal(str(prev_month_data.total_profit)) if prev_month_data.total_profit else Decimal('0.0')
        
        comparisons['mom_sales'] = prev_month_sales
        comparisons['mom_profit'] = prev_month_profit
        
        if prev_month_sales > 0:
            sales_diff = Decimal(str(self.metrics['total_sales'])) - prev_month_sales
            comparisons['mom_change'] = (sales_diff / prev_month_sales * 100)
        
        # Year-over-year comparison
        last_year = self.first_day - timedelta(days=365)
        last_year_last_day = (last_year.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        last_year_data = db.session.query(
            func.sum(Sale.total).label('total_sales'),
            func.sum(Sale.profit).label('total_profit')
        ).filter(
            Sale.date >= last_year.replace(day=1),
            Sale.date <= last_year_last_day
        ).first()
        
        last_year_sales = Decimal(str(last_year_data.total_sales)) if last_year_data.total_sales else Decimal('0.0')
        last_year_profit = Decimal(str(last_year_data.total_profit)) if last_year_data.total_profit else Decimal('0.0')
        
        comparisons['yoy_sales'] = last_year_sales
        comparisons['yoy_profit'] = last_year_profit
        
        if last_year_sales > 0:
            sales_diff = Decimal(str(self.metrics['total_sales'])) - last_year_sales
            comparisons['yoy_change'] = (sales_diff / last_year_sales * 100)
        
        # Convert all Decimal values to float for JSON serialization
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in comparisons.items()}
    
    def generate_time_analytics(self):
        """Generate daily and weekly trends with accurate financial calculations"""
        # Initialize daily data structure
        daily_data = OrderedDict()
        for day in range(1, self.days_in_month + 1):
            date = self.first_day.replace(day=day)
            daily_data[date] = {
                'date': date,
                'sales': Decimal('0.0'),
                'transactions': 0,
                'profit': Decimal('0.0'),
                'avg_sale': Decimal('0.0'),
                'products': 0,
                'cost': Decimal('0.0'),
                'margin': Decimal('0.0')
            }

        # Populate daily data
        for sale in self.sales:
            day_key = sale.date.replace(hour=0, minute=0, second=0, microsecond=0)
            if day_key in daily_data:
                daily = daily_data[day_key]
                sale_total = Decimal(str(sale.total))
                sale_profit = Decimal(str(sale.profit)) if sale.profit else Decimal('0.0')
                
                daily['sales'] += sale_total
                daily['transactions'] += 1
                daily['profit'] += sale_profit
                
                # Calculate product quantities and costs
                for item in sale.cart_items:
                    daily['products'] += item.quantity
                    if item.product and item.product.cost_price:
                        daily['cost'] += Decimal(str(item.product.cost_price)) * item.quantity
                
                # Calculate margin if we have sales
                if daily['sales'] > 0:
                    daily['margin'] = ((daily['sales'] - daily['cost']) / daily['sales'] * 100)
                
                # Calculate average sale
                if daily['transactions'] > 0:
                    daily['avg_sale'] = daily['sales'] / daily['transactions']

        # Weekly breakdown
        weekly_data = {
            'Week 1': {'sales': Decimal('0.0'), 'transactions': 0, 'profit': Decimal('0.0'), 'days': 0, 'products': 0},
            'Week 2': {'sales': Decimal('0.0'), 'transactions': 0, 'profit': Decimal('0.0'), 'days': 0, 'products': 0},
            'Week 3': {'sales': Decimal('0.0'), 'transactions': 0, 'profit': Decimal('0.0'), 'days': 0, 'products': 0},
            'Week 4': {'sales': Decimal('0.0'), 'transactions': 0, 'profit': Decimal('0.0'), 'days': 0, 'products': 0},
            'Week 5': {'sales': Decimal('0.0'), 'transactions': 0, 'profit': Decimal('0.0'), 'days': 0, 'products': 0}
        }

        for day in daily_data.values():
            week_num = min((day['date'].day - 1) // 7 + 1, 5)
            week_key = f'Week {week_num}'
            weekly = weekly_data[week_key]
            
            weekly['sales'] += day['sales']
            weekly['transactions'] += day['transactions']
            weekly['profit'] += day['profit']
            weekly['days'] += 1
            weekly['products'] += day['products']

        # Convert all Decimal values to float for JSON serialization
        def convert_decimals(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            elif isinstance(obj, dict):
                return {k: convert_decimals(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_decimals(x) for x in obj]
            return obj

        return {
            'daily': convert_decimals(list(daily_data.values())),
            'weekly': convert_decimals(weekly_data),
            'hourly': self._generate_hourly_analysis()
        }
    
    def generate_product_analytics(self):
        """Analyze product performance with precise financial calculations"""
        product_metrics = defaultdict(lambda: {
            'quantity': 0,
            'revenue': Decimal('0.0'),
            'cost': Decimal('0.0'),
            'profit': Decimal('0.0'),
            'margin': Decimal('0.0'),
            'transactions': set(),
            'categories': set()
        })

        for sale in self.sales:
            for item in sale.cart_items:
                product = item.product
                if not product:
                    continue
                    
                item_revenue = Decimal(str(item.total_price))
                item_cost = Decimal(str(product.cost_price)) * item.quantity if product.cost_price else Decimal('0.0')
                item_profit = item_revenue - item_cost
                
                pm = product_metrics[product.name]
                pm['quantity'] += item.quantity
                pm['revenue'] += item_revenue
                pm['cost'] += item_cost
                pm['profit'] += item_profit
                pm['transactions'].add(sale.id)
                if product.category:
                    pm['categories'].add(product.category.name)

        # Calculate metrics for each product
        top_products = []
        for name, data in product_metrics.items():
            margin = (data['profit'] / data['revenue'] * 100) if data['revenue'] > 0 else Decimal('0.0')
            top_products.append({
                'name': name,
                'quantity': data['quantity'],
                'revenue': data['revenue'],
                'cost': data['cost'],
                'profit': data['profit'],
                'margin': margin,
                'transactions': len(data['transactions']),
                'categories': list(data['categories']),
                'avg_order_value': data['revenue'] / len(data['transactions']) if data['transactions'] else Decimal('0.0'),
                'avg_quantity': data['quantity'] / len(data['transactions']) if data['transactions'] else Decimal('0.0')
            })

        # Sort by revenue and convert Decimals to floats
        top_products_sorted = sorted(top_products, key=lambda x: x['revenue'], reverse=True)[:15]
        return {
            'top_products': [{k: float(v) if isinstance(v, Decimal) else v for k, v in p.items()} 
                            for p in top_products_sorted],
            'category_breakdown': self._generate_category_analysis(product_metrics)
        }

    def _generate_category_analysis(self, product_metrics):
        """Generate product category breakdown from product metrics"""
        category_metrics = defaultdict(lambda: {
            'revenue': Decimal('0.0'),
            'cost': Decimal('0.0'),
            'profit': Decimal('0.0'),
            'products': 0,
            'quantity': 0,
            'transactions': set()
        })

        for product_data in product_metrics.values():
            for category in product_data['categories']:
                cm = category_metrics[category]
                cm['revenue'] += product_data['revenue']
                cm['cost'] += product_data['cost']
                cm['profit'] += product_data['profit']
                cm['products'] += 1
                cm['quantity'] += product_data['quantity']
                cm['transactions'].update(product_data['transactions'])

        # Calculate category metrics
        category_breakdown = []
        for name, data in category_metrics.items():
            margin = (data['profit'] / data['revenue'] * 100) if data['revenue'] > 0 else Decimal('0.0')
            category_breakdown.append({
                'name': name,
                'revenue': data['revenue'],
                'cost': data['cost'],
                'profit': data['profit'],
                'margin': margin,
                'products': data['products'],
                'quantity': data['quantity'],
                'transactions': len(data['transactions']),
                'avg_sale_value': data['revenue'] / len(data['transactions']) if data['transactions'] else Decimal('0.0')
            })

        # Sort by revenue and convert Decimals to floats
        category_breakdown_sorted = sorted(category_breakdown, key=lambda x: x['revenue'], reverse=True)
        return [{k: float(v) if isinstance(v, Decimal) else v for k, v in cb.items()} 
               for cb in category_breakdown_sorted]

    def generate_staff_analytics(self):
        """Analyze staff performance with accurate financial metrics"""
        staff_performance = defaultdict(lambda: {
            'sales_count': 0,
            'sales_value': Decimal('0.0'),
            'profit': Decimal('0.0'),
            'products_sold': 0,
            'transactions': set(),
            'avg_sale': Decimal('0.0'),
            'profit_margin': Decimal('0.0'),
            'products_per_sale': Decimal('0.0')
        })

        for sale in self.sales:
            if not sale.user:
                continue
                
            sale_value = Decimal(str(sale.total))
            sale_profit = Decimal(str(sale.profit)) if sale.profit else Decimal('0.0')
            products_sold = sum(item.quantity for item in sale.cart_items)
            
            staff = staff_performance[sale.user.username]
            staff['sales_count'] += 1
            staff['sales_value'] += sale_value
            staff['profit'] += sale_profit
            staff['products_sold'] += products_sold
            staff['transactions'].add(sale.id)

        # Calculate derived metrics
        for staff in staff_performance.values():
            if staff['sales_count'] > 0:
                staff['avg_sale'] = staff['sales_value'] / staff['sales_count']
                staff['products_per_sale'] = Decimal(staff['products_sold']) / staff['sales_count']
                if staff['sales_value'] > 0:
                    staff['profit_margin'] = (staff['profit'] / staff['sales_value'] * 100)

        # Convert all Decimal values to float for JSON serialization
        return {k: {m: float(v) if isinstance(v, Decimal) else v for m, v in data.items()} 
               for k, data in staff_performance.items()}

    def generate_payment_analysis(self):
        """Analyze payment methods with precise financial calculations"""
        payment_analysis = defaultdict(lambda: {
            'total': Decimal('0.0'),
            'count': 0,
            'avg_amount': Decimal('0.0'),
            'transactions': set()
        })

        for sale in self.sales:
            method = (sale.payment_method or 'unknown').lower()
            sale_amount = Decimal(str(sale.total))
            
            payment_analysis[method]['total'] += sale_amount
            payment_analysis[method]['count'] += 1
            payment_analysis[method]['transactions'].add(sale.id)

        # Calculate averages
        for method in payment_analysis:
            if payment_analysis[method]['count'] > 0:
                payment_analysis[method]['avg_amount'] = (
                    payment_analysis[method]['total'] / payment_analysis[method]['count']
                )

        # Convert all Decimal values to float for JSON serialization
        return {k: {m: float(v) if isinstance(v, Decimal) else v for m, v in data.items()} 
               for k, data in payment_analysis.items()}

    def generate_customer_analysis(self):
        """Analyze customer types with accurate financial metrics"""
        customer_analysis = defaultdict(lambda: {
            'total': Decimal('0.0'),
            'count': 0,
            'avg_amount': Decimal('0.0'),
            'transactions': set(),
            'profit': Decimal('0.0')
        })

        for sale in self.sales:
            c_type = getattr(sale, 'customer_type', 'regular') or 'regular'
            c_type = c_type.lower()
            sale_amount = Decimal(str(sale.total))
            sale_profit = Decimal(str(sale.profit)) if sale.profit else Decimal('0.0')
            
            customer_analysis[c_type]['total'] += sale_amount
            customer_analysis[c_type]['count'] += 1
            customer_analysis[c_type]['transactions'].add(sale.id)
            customer_analysis[c_type]['profit'] += sale_profit

        # Calculate averages and margins
        for c_type in customer_analysis:
            if customer_analysis[c_type]['count'] > 0:
                customer_analysis[c_type]['avg_amount'] = (
                    customer_analysis[c_type]['total'] / customer_analysis[c_type]['count']
                )
            if customer_analysis[c_type]['total'] > 0:
                customer_analysis[c_type]['profit_margin'] = (
                    customer_analysis[c_type]['profit'] / customer_analysis[c_type]['total'] * 100
                )

        # Convert all Decimal values to float for JSON serialization
        return {k: {m: float(v) if isinstance(v, Decimal) else v for m, v in data.items()} 
               for k, data in customer_analysis.items()}

    def prepare_chart_data(self):
        """Prepare data for visualization charts with robust error handling"""
        chart_data = {
            'daily': {
                'labels': [],
                'sales': [],
                'transactions': [],
                'avg_sale': [],
                'margin': []
            },
            'weekly': {
                'labels': [],
                'sales': [],
                'transactions': [],
                'profit': []
            },
            'products': {
                'labels': [],
                'revenue': [],
                'margin': []
            },
            'categories': {
                'labels': [],
                'revenue': [],
                'margin': []
            },
            'payment_methods': {
                'labels': [],
                'total': [],
                'count': []
            }
        }

        try:
            # Daily data
            if hasattr(self, 'time_analytics') and 'daily' in self.time_analytics:
                daily = self.time_analytics['daily']
                chart_data['daily']['labels'] = [d['date'].strftime('%d') for d in daily]
                chart_data['daily']['sales'] = [d['sales'] for d in daily]
                chart_data['daily']['transactions'] = [d['transactions'] for d in daily]
                chart_data['daily']['avg_sale'] = [d['avg_sale'] for d in daily]
                chart_data['daily']['margin'] = [d['margin'] for d in daily]

            # Weekly data
            if hasattr(self, 'time_analytics') and 'weekly' in self.time_analytics:
                weekly = self.time_analytics['weekly']
                chart_data['weekly']['labels'] = list(weekly.keys())
                chart_data['weekly']['sales'] = [w['sales'] for w in weekly.values()]
                chart_data['weekly']['transactions'] = [w['transactions'] for w in weekly.values()]
                chart_data['weekly']['profit'] = [w['profit'] for w in weekly.values()]

            # Product data
            if hasattr(self, 'product_analytics') and 'top_products' in self.product_analytics:
                products = self.product_analytics['top_products']
                chart_data['products']['labels'] = [p['name'] for p in products]
                chart_data['products']['revenue'] = [p['revenue'] for p in products]
                chart_data['products']['margin'] = [p['margin'] for p in products]

            # Category data
            if hasattr(self, 'product_analytics') and 'category_breakdown' in self.product_analytics:
                categories = self.product_analytics['category_breakdown']
                chart_data['categories']['labels'] = [c['name'] for c in categories]
                chart_data['categories']['revenue'] = [c['revenue'] for c in categories]
                chart_data['categories']['margin'] = [c['margin'] for c in categories]

            # Payment methods
            if hasattr(self, 'payment_analytics'):
                payments = self.payment_analytics.items()
                chart_data['payment_methods']['labels'] = [k for k, v in payments]
                chart_data['payment_methods']['total'] = [v['total'] for k, v in payments]
                chart_data['payment_methods']['count'] = [v['count'] for k, v in payments]

        except Exception as e:
            current_app.logger.error(f"Error preparing chart data: {str(e)}")

        return chart_data

    def generate_context(self, full_report=True):
        """Generate complete context dictionary with proper date handling"""
        if not self.initialize_dates():
            raise ValueError("Invalid date parameters")
        
        if not self.fetch_sales_data():
            raise Exception("Failed to fetch sales data")
        
        self.metrics = self.calculate_core_metrics()
        self.time_analytics = self.generate_time_analytics()
        self.product_analytics = self.generate_product_analytics()
        self.payment_analytics = self.generate_payment_analysis()
        self.comparisons = self.calculate_comparisons()
        
        if full_report:
            self.staff_analytics = self.generate_staff_analytics()
            self.customer_analytics = self.generate_customer_analysis()

        self.chart_data = self.prepare_chart_data()

        # Ensure all dates are properly formatted
        base_context = {
            'report_date': {
                'month': self.month_str,  # Keep as string 'YYYY-MM'
                'display': self.report_month.strftime('%B %Y'),  # Formatted string
                'prev_month': self.prev_month.strftime('%Y-%m'),  # String
                'next_month': self.next_month.strftime('%Y-%m'),  # String
                'current_month': datetime.utcnow().strftime('%Y-%m'),  # String
                'days_in_month': self.days_in_month,  # Integer
                'first_day': self.first_day,  # Keep as date object
                'last_day': self.last_day,    # Keep as date object
                'first_day_str': self.first_day.strftime('%Y-%m-%d'),  # String version
                'last_day_str': self.last_day.strftime('%Y-%m-%d')     # String version
            },
            'metrics': self.metrics,
            'comparisons': self.comparisons,
            'time_analytics': self.time_analytics,
            'product_analytics': self.product_analytics,
            'payment_analytics': self.payment_analytics,
            'chart_data': self.chart_data
        }

        if full_report:
            full_context = {
                **base_context,
                'staff_analytics': self.staff_analytics,
                'customer_analytics': self.customer_analytics
            }
            return full_context
        
        return base_context

    def _generate_hourly_analysis(self):
        """Generate hourly sales patterns"""
        hourly_data = {hour: {
            'sales': Decimal('0.0'),
            'transactions': 0,
            'avg_sale': Decimal('0.0')
        } for hour in range(24)}

        for sale in self.sales:
            hour = sale.date.hour
            sale_amount = Decimal(str(sale.total))
            
            hourly_data[hour]['sales'] += sale_amount
            hourly_data[hour]['transactions'] += 1

        # Calculate averages
        for hour in hourly_data.values():
            if hour['transactions'] > 0:
                hour['avg_sale'] = hour['sales'] / hour['transactions']

        # Convert to list format and Decimal to float
        return {
            'labels': [f"{h:02d}:00" for h in range(24)],
            'sales': [float(h['sales']) for h in hourly_data.values()],
            'transactions': [h['transactions'] for h in hourly_data.values()],
            'avg_sale': [float(h['avg_sale']) for h in hourly_data.values()]
        }
        
@sales_bp.route('/reports/monthly-analytics', methods=['GET'])
@login_required
def monthly_sales_analytics():
    """Unified Monthly Sales Analytics (HTMX + full)"""
    try:
        month = request.args.get('month')  # e.g., '2025-06'
        analyzer = MonthlySalesAnalyzer(month)
        context = analyzer.generate_context(full_report=not request.headers.get('HX-Request'))

        return render_htmx(
            'reports/fragments/_monthly_sales_fragment.html',
            **context
        )
    
    except Exception as e:
        current_app.logger.error(f"Monthly analytics error: {str(e)}", exc_info=True)

        if request.headers.get('HX-Request'):
            return render_template(
                'partials/_error_message.html',
                message="Failed to load analytics: " + str(e)
            ), 500

        flash("An error occurred while generating the monthly report. Please try again.", "danger")
        return redirect(url_for('sales_bp.sales_dashboard'))






from flask import make_response
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from io import BytesIO

@sales_bp.route('/reports/daily/export-pdf', methods=['GET'])
@login_required
def export_daily_report_pdf():
    try:
        date_str = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Generate the report data
        report_data = generate_daily_report_data(report_date)
        
        # Create PDF buffer
        buffer = BytesIO()
        
        # Create PDF document
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        elements = []
        styles = getSampleStyleSheet()
        
        # Add title
        elements.append(Paragraph(f"Daily Sales Report - {report_date}", styles['Title']))
        elements.append(Spacer(1, 12))
        
        # Add summary table
        summary_data = [
            ["Total Sales", f"${report_data['summary']['total_sales']}"],
            ["Total Transactions", report_data['summary']['total_transactions']],
            ["Average Sale", f"${report_data['summary']['avg_sale']}"],
            ["Total Profit", f"${report_data['summary']['total_profit']}"]
        ]
        summary_table = Table(summary_data, colWidths=[200, 200])
        elements.append(summary_table)
        elements.append(Spacer(1, 24))
        
        # Add product performance
        elements.append(Paragraph("Top Products", styles['Heading2']))
        product_data = [["Product", "Quantity", "Revenue"]] + [
            [product, str(data['quantity']), f"${data['revenue']}"] 
            for product, data in report_data['product_performance']
        ]
        product_table = Table(product_data, colWidths=[200, 100, 100])
        elements.append(product_table)
        
        # Build PDF
        doc.build(elements)
        
        # Prepare response
        buffer.seek(0)
        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=daily_report_{report_date}.pdf'
        
        return response
        
    except Exception as e:
        return str(e), 500







from flask import Response
from openpyxl import Workbook
from io import BytesIO

@sales_bp.route('/reports/daily/export-excel', methods=['GET'])
@login_required
def export_daily_report_excel():
    try:
        date_str = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Generate report data
        report_data = generate_daily_report_data(report_date)
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = f"Sales {report_date}"
        
        # Add headers
        ws.append(["Daily Sales Report", report_date.strftime('%Y-%m-%d')])
        ws.append([])  # Empty row
        
        # Add summary
        ws.append(["Summary"])
        ws.append(["Total Sales", report_data['summary']['total_sales']])
        ws.append(["Total Transactions", report_data['summary']['total_transactions']])
        ws.append(["Average Sale", report_data['summary']['avg_sale']])
        ws.append(["Total Profit", report_data['summary']['total_profit']])
        ws.append([])
        
        # Add payment methods
        ws.append(["Payment Methods"])
        for method, amount in report_data['payment_methods'].items():
            ws.append([method.capitalize(), amount])
        ws.append([])
        
        # Add product performance
        ws.append(["Top Products"])
        ws.append(["Product", "Quantity", "Revenue"])
        for product, data in report_data['product_performance']:
            ws.append([product, data['quantity'], data['revenue']])
        ws.append([])
        
        # Create response
        excel_buffer = BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)
        
        response = Response(
            excel_buffer,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment;filename=daily_sales_{report_date}.xlsx"
            }
        )
        
        return response
        
    except Exception as e:
        return str(e), 500        
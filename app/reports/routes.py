from datetime import datetime, timedelta
from collections import defaultdict, Counter
import logging
import statistics
from math import ceil
from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func, extract, and_, or_, case, Date
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import (Product, Sale, CartItem, PriceChange, StockLog, 
                       User,  Category)
from flask_login import login_required
from decimal import Decimal
from datetime import datetime, date
from sqlalchemy import select
from app.utils.render import render_htmx
# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

reports_bp = Blueprint('reports', __name__)


def get_time_filter(time_period, date_column=Sale.date):
    """Create time filters with better error handling"""
    try:
        now = datetime.utcnow()
        periods = {
            'today': timedelta(days=1),
            'week': timedelta(weeks=1),
            'month': timedelta(days=30),
            'year': timedelta(days=365),
            'all': timedelta(days=365*10)  # 10 years as "all time"
        }
        
        if time_period not in periods:
            time_period = 'month'  # Default to month
            
        return date_column >= (now - periods[time_period])
        
    except Exception as e:
        logger.error(f"Error creating time filter for period {time_period}: {str(e)}")
        return date_column >= (datetime.utcnow() - timedelta(days=30))  # Fallback to month



def safe_divide(numerator, denominator, default=0):
    """Safe division to avoid division by zero"""
    return numerator / denominator if denominator else default

def calculate_total_revenue(product_id, time_period='month'):
    """Calculate total revenue for a product"""
    time_filter = get_time_filter(time_period)
    revenue = db.session.query(
        func.sum(CartItem.quantity * Product.selling_price)
    ).join(Product).join(Sale).filter(
        Product.id == product_id,
        time_filter
    ).scalar()
    return revenue or 0

def calculate_revenue_trend(product_id, time_period):
    """Calculate revenue trend compared to previous period"""
    current = calculate_total_revenue(product_id, time_period)
    previous = calculate_total_revenue(product_id, f"previous_{time_period}")
    return round(safe_divide((current - previous), previous, 0) * 100, 1)

def calculate_total_units_sold(product_id, time_period='month'):
    """Calculate total units sold"""
    time_filter = get_time_filter(time_period)
    units = db.session.query(
        func.sum(CartItem.quantity)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        time_filter
    ).scalar()
    return units or 0

def calculate_sales_trend(product_id, time_period):
    """Calculate sales trend compared to previous period"""
    current = calculate_total_units_sold(product_id, time_period)
    previous = calculate_total_units_sold(product_id, f"previous_{time_period}")
    return round(safe_divide((current - previous), previous, 0) * 100, 1)

def calculate_avg_profit_margin(product_id, time_period='month'):
    """Calculate average profit margin"""
    time_filter = get_time_filter(time_period)
    margins = db.session.query(
        (Product.selling_price - Product.cost_price) / Product.selling_price * 100
    ).join(CartItem).join(Sale).filter(
        Product.id == product_id,
        time_filter,
        Product.selling_price > 0
    ).all()
    return round(statistics.mean([m[0] for m in margins]), 1) if margins else 0

def calculate_margin_trend(product_id, time_period):
    """Calculate profit margin trend"""
    current = calculate_avg_profit_margin(product_id, time_period)
    previous = calculate_avg_profit_margin(product_id, f"previous_{time_period}")
    return round(current - previous, 1)

def get_peak_sales_day(product_id, time_period='month'):
    """Get day with highest sales volume"""
    time_filter = get_time_filter(time_period)
    result = db.session.query(
        extract('dow', Sale.date).label('day_of_week'),
        func.sum(CartItem.quantity).label('total_units')
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        time_filter
    ).group_by('day_of_week').order_by(func.sum(CartItem.quantity).desc()).first()
    
    if result:
        days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 
               'Thursday', 'Friday', 'Saturday']
        return days[int(result.day_of_week)]
    return "No sales data"

def get_avg_days_between_sales(product_id, time_period='month'):
    """Calculate average days between sales with comprehensive error handling
    
    Args:
        product_id (int): ID of the product to analyze
        time_period (str): Time period filter ('day', 'week', 'month', 'year', 'all')
    
    Returns:
        float: Average days between sales, or 0 if insufficient data
    """
    try:
        # Validate product exists first
        if not Product.query.get(product_id):
            logger.warning(f"Product {product_id} not found")
            return 0

        time_filter = get_time_filter(time_period)
        
        # Get distinct sale dates with explicit date formatting
        sale_dates = db.session.query(
            func.date(Sale.date).label('sale_date')  # Use func.date() for consistent formatting
        ).join(
            CartItem, Sale.id == CartItem.sale_id
        ).filter(
            CartItem.product_id == product_id,
            time_filter,
            Sale.date.isnot(None)  # Explicitly filter out NULL dates
        ).distinct().order_by('sale_date').all()

        # Parse and validate dates
        valid_dates = []
        for date_record in sale_dates:
            date_value = date_record[0]
            
            # Skip None values (shouldn't happen due to filter, but just in case)
            if date_value is None:
                continue
                
            # Handle different date types
            if isinstance(date_value, (datetime, date)):
                valid_date = date_value.date() if isinstance(date_value, datetime) else date_value
                valid_dates.append(valid_date)
            elif isinstance(date_value, str):
                try:
                    # Only accept complete date strings
                    if len(date_value) == 10:  # Full date 'YYYY-MM-DD'
                        valid_dates.append(datetime.strptime(date_value, '%Y-%m-%d').date())
                    else:
                        logger.debug(f"Skipping incomplete date string: {date_value}")
                        continue
                except ValueError as e:
                    logger.warning(f"Invalid date format '{date_value}': {str(e)}")
                    continue
        
        # Require at least 2 valid dates to calculate an average
        if len(valid_dates) < 2:
            logger.info(f"Insufficient valid dates ({len(valid_dates)}) for product {product_id}")
            return 0
            
        # Calculate time differences between consecutive sales
        deltas = []
        prev_date = valid_dates[0]
        for current_date in valid_dates[1:]:
            delta = (current_date - prev_date).days
            if delta > 0:  # Only count positive deltas
                deltas.append(delta)
            prev_date = current_date
        
        if not deltas:
            return 0
            
        # Calculate average with protection against statistical errors
        try:
            avg_days = statistics.mean(deltas)
            return round(avg_days, 1)
        except statistics.StatisticsError:
            return 0
        
    except SQLAlchemyError as e:
        logger.error(f"Database error calculating days between sales for product {product_id}: {str(e)}")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error processing product {product_id}: {str(e)}", exc_info=True)
        return 0
        
def get_max_stock_observed(product_id):
    max_stock = db.session.query(
        db.func.max(StockLog.new_stock)
    ).filter_by(product_id=product_id).scalar()

    product = Product.query.get(product_id)

    return max_stock or (product.stock if product else 0)


def get_stockout_count(product_id, time_period='month'):
    """Count stockout occurrences"""
    time_filter = get_time_filter(time_period, StockLog.date)
    count = db.session.query(
        func.count(StockLog.id)
    ).filter_by(product_id=product_id).filter(
        StockLog.new_stock == 0,
        time_filter
    ).scalar()
    return count or 0

def get_avg_monthly_usage(product_id):
    """Calculate average monthly usage"""
    monthly_usage = db.session.query(
        extract('year', Sale.date).label('year'),
        extract('month', Sale.date).label('month'),
        func.sum(CartItem.quantity).label('units')
    ).join(CartItem).filter(
        CartItem.product_id == product_id
    ).group_by('year', 'month').all()
    
    if not monthly_usage:
        return 0
        
    avg = statistics.mean([m.units for m in monthly_usage])
    return round(avg, 1)

def get_stock_cover_days(product_id):
    """Calculate stock cover in days"""
    avg_monthly = get_avg_monthly_usage(product_id)
    if not avg_monthly:
        return 0
        
    current_stock = db.session.query(
        Product.stock
    ).filter_by(id=product_id).scalar() or 0
    
    return ceil(current_stock / (avg_monthly / 30))  # Convert monthly to daily average

def get_best_selling_month(product_id):
    """Get the month with highest sales historically"""
    result = db.session.query(
        extract('month', Sale.date).label('month'),
        func.sum(CartItem.quantity).label('units')
    ).join(CartItem).filter(
        CartItem.product_id == product_id
    ).group_by('month').order_by(func.sum(CartItem.quantity).desc()).first()
    
    if result:
        months = ['January', 'February', 'March', 'April', 'May', 'June',
                 'July', 'August', 'September', 'October', 'November', 'December']
        return months[int(result.month)-1]
    return "No data"

def get_revenue_growth(product_id, time_period='month'):
    """Calculate year-over-year revenue growth"""
    current_year = db.session.query(
        func.sum(CartItem.quantity * Product.selling_price)
    ).join(Product).join(Sale).filter(
        Product.id == product_id,
        extract('year', Sale.date) == datetime.utcnow().year
    ).scalar() or 0
    
    previous_year = db.session.query(
        func.sum(CartItem.quantity * Product.selling_price)
    ).join(Product).join(Sale).filter(
        Product.id == product_id,
        extract('year', Sale.date) == datetime.utcnow().year - 1
    ).scalar() or 0
    
    return round(safe_divide((current_year - previous_year), previous_year, 0) * 100, 1)

def get_sales_growth(product_id, time_period='month'):
    """Calculate year-over-year sales growth"""
    current_year = db.session.query(
        func.sum(CartItem.quantity)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        extract('year', Sale.date) == datetime.utcnow().year
    ).scalar() or 0
    
    previous_year = db.session.query(
        func.sum(CartItem.quantity)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        extract('year', Sale.date) == datetime.utcnow().year - 1
    ).scalar() or 0
    
    return round(safe_divide((current_year - previous_year), previous_year, 0) * 100, 1)

def get_price_change_count(product_id, time_period='month'):
    """Count price changes in period"""
    time_filter = get_time_filter(time_period, PriceChange.changed_at)
    count = db.session.query(
        func.count(PriceChange.id)
    ).filter_by(
        product_id=product_id,
        change_type='selling_price_update'
    ).filter(time_filter).scalar()
    return count or 0

def get_suggested_price(product_id):
    """Calculate suggested price with proper decimal handling"""
    try:
        # Get cost price as float
        cost = float(Product.query.get(product_id).cost_price)
        
        # Calculate average margin
        avg_margin = db.session.query(
            func.avg((Product.selling_price - Product.cost_price) / Product.cost_price)
        ).filter(Product.id != product_id).scalar() or 0.3
        
        # Ensure avg_margin is float
        avg_margin = float(avg_margin) if isinstance(avg_margin, Decimal) else avg_margin
        
        suggested = cost * (1 + avg_margin)
        return round(suggested, 2)
        
    except Exception as e:
        logger.error(f"Error calculating suggested price: {str(e)}")
        return 0.0

def get_avg_quantity_per_order(product_id, time_period='month'):
    """Calculate average quantity per order"""
    time_filter = get_time_filter(time_period)
    avg = db.session.query(
        func.avg(CartItem.quantity)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        time_filter
    ).scalar()
    return round(avg, 1) if avg else 0

def get_repeat_purchase_rate(product_id, time_period='month'):
    """Estimate repeat purchase rate based on sales frequency patterns"""
    try:
        time_filter = get_time_filter(time_period)
        
        # Get all sales dates for this product
        sale_dates = db.session.query(
            Sale.date
        ).join(CartItem).filter(
            CartItem.product_id == product_id,
            time_filter
        ).order_by(Sale.date).all()
        
        if len(sale_dates) < 3:
            return 0.0  # Not enough data to determine patterns
            
        # Calculate time between purchases
        time_deltas = []
        for i in range(1, len(sale_dates)):
            delta = (sale_dates[i][0] - sale_dates[i-1][0]).total_seconds() / 3600  # in hours
            time_deltas.append(delta)
        
        avg_hours_between = statistics.mean(time_deltas)
        
        # Estimate repeat rate based on frequency
        if avg_hours_between < 24:
            return 75.0  # Very frequent purchases (likely repeat customers)
        elif avg_hours_between < 168:  # 1 week
            return 50.0
        elif avg_hours_between < 720:  # 1 month
            return 25.0
        else:
            return 10.0  # Infrequent purchases
            
    except Exception as e:
        logger.error(f"Error estimating repeat purchases: {str(e)}")
        return 0.0

def get_frequently_bought_with(product_id, time_period='month', limit=3):
    """Find products commonly purchased together"""
    try:
        time_filter = get_time_filter(time_period)

        # Get sales that included our product
        sales_with_product = db.session.query(
            Sale.id
        ).join(CartItem).filter(
            CartItem.product_id == product_id,
            time_filter
        ).subquery()

        # Find other products in those sales
        frequent_products = db.session.query(
            Product.name,
            func.count(CartItem.product_id).label('count')
        ).join(CartItem).filter(
            CartItem.sale_id.in_(select(sales_with_product.c.id)),
            CartItem.product_id != product_id
        ).group_by(Product.name).order_by(func.count(CartItem.product_id).desc()).limit(limit).all()

        return [p[0] for p in frequent_products]

    except Exception as e:
        logger.error(f"Error finding frequently bought items: {str(e)}", exc_info=True)
        return []


from sqlalchemy import text

def get_analytics_months(product_id, limit=12):
    try:
        month_label = func.to_char(Sale.date, 'YYYY-MM').label('month')

        results = db.session.query(
            month_label
        ).select_from(Sale) \
         .join(CartItem, Sale.id == CartItem.sale_id) \
         .filter(
            CartItem.product_id == product_id,
            Sale.date != None
         ).group_by(month_label) \
         .order_by(month_label.desc()) \
         .limit(limit) \
         .all()

        return [r.month for r in reversed(results)]  # Chronological
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error getting analytics months: {str(e)}", exc_info=True)
        return []



def get_units_sold_by_month(product_id, limit=12):
    """PostgreSQL-safe version to get units sold by month"""
    try:
        months = get_analytics_months(product_id, limit)
        if not months:
            return []

        # Use PostgreSQL to_char instead of SQLite strftime
        month_label = func.to_char(Sale.date, 'YYYY-MM').label('month')

        results = db.session.query(
            month_label,
            func.sum(CartItem.quantity).label('units')
        ).select_from(Sale) \
         .join(CartItem, Sale.id == CartItem.sale_id) \
         .filter(
            CartItem.product_id == product_id,
            month_label.in_(months)
        ).group_by(month_label) \
         .order_by(month_label) \
         .all()

        data = {r.month: r.units for r in results}
        return [data.get(m, 0) for m in months]

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error getting units by month for product {product_id}: {str(e)}", exc_info=True)
        return []


def get_revenue_by_month(product_id, limit=12):
    """Get monthly revenue for a product, grouped by month (PostgreSQL-safe)"""
    try:
        # Get target months from another function
        months = get_analytics_months(product_id, limit)
        if not months:
            return []

        # Define the month label using PostgreSQL-compatible to_char
        month_label = func.to_char(Sale.date, 'YYYY-MM').label('month')

        results = db.session.query(
            month_label,
            func.sum(CartItem.quantity * Product.selling_price).label('revenue')
        ).select_from(Sale) \
         .join(CartItem, Sale.id == CartItem.sale_id) \
         .join(Product, CartItem.product_id == Product.id) \
         .filter(
            Product.id == product_id,
            month_label.in_(months)
         ).group_by(month_label) \
         .order_by(month_label) \
         .all()

        # Build revenue per month
        data = {m[0]: float(m[1]) for m in results}
        return [data.get(m, 0.0) for m in months]

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error getting revenue by month: {str(e)}", exc_info=True)
        return []


def get_price_change_dates(product_id, limit=12):
    """Get price change dates for chart"""
    try:
        changes = PriceChange.query.filter_by(
            product_id=product_id,
            change_type='selling_price_update'
        ).order_by(PriceChange.changed_at.desc()).limit(limit).all()

        return [c.changed_at.strftime('%Y-%m-%d') for c in reversed(changes)] if changes else []

    except Exception as e:
        db.session.rollback()  # Rollback in case session is in a failed state
        logger.error(f"Error getting price change dates for product {product_id}: {e}", exc_info=True)
        return []


def get_price_history(product_id, limit=12):
    """Get price history for chart"""
    changes = PriceChange.query.filter_by(
        product_id=product_id,
        change_type='selling_price_update'
    ).order_by(PriceChange.changed_at.desc()).limit(limit).all()
    
    return [float(c.new_price) for c in reversed(changes)] if changes else []

def get_sales_by_day_of_week(product_id, time_period='month'):
    """Get sales distribution by day of week"""
    time_filter = get_time_filter(time_period)
    
    # Initialize with zeros for all days
    day_map = {i: 0 for i in range(7)}
    
    results = db.session.query(
        extract('dow', Sale.date).label('day_of_week'),
        func.sum(CartItem.quantity).label('units')
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        time_filter
    ).group_by('day_of_week').all()
    
    for day, units in results:
        day_map[int(day)] = units
    
    # Return in order Monday (0) to Sunday (6)
    return [day_map[i] for i in range(7)]



@reports_bp.route('/products/<int:product_id>/report')
def product_report(product_id):

    product = Product.query.get_or_404(product_id)
    time_period = request.args.get('time_period', 'month')
    
    analytics = {
        'total_revenue': calculate_total_revenue(product_id, time_period),
        'revenue_trend': calculate_revenue_trend(product_id, time_period),
        'total_units_sold': calculate_total_units_sold(product_id, time_period),
        'sales_trend': calculate_sales_trend(product_id, time_period),
        'avg_profit_margin': calculate_avg_profit_margin(product_id, time_period),
        'margin_trend': calculate_margin_trend(product_id, time_period),
        'peak_sales_day': get_peak_sales_day(product_id, time_period),
        'avg_days_between_sales': get_avg_days_between_sales(product_id, time_period),
        'max_stock_observed': get_max_stock_observed(product_id),
        'stockout_count': get_stockout_count(product_id, time_period),
        'avg_monthly_usage': get_avg_monthly_usage(product_id),
        'stock_cover_days': get_stock_cover_days(product_id),
        'best_selling_month': get_best_selling_month(product_id),
        'revenue_growth': get_revenue_growth(product_id, time_period),
        'sales_growth': get_sales_growth(product_id, time_period),
        'price_change_count': get_price_change_count(product_id, time_period),
        'suggested_price': get_suggested_price(product_id),
        'avg_quantity_per_order': get_avg_quantity_per_order(product_id, time_period),
        'repeat_purchase_rate': get_repeat_purchase_rate(product_id, time_period),
        'frequently_bought_with': get_frequently_bought_with(product_id, time_period),
        'months': get_analytics_months(product_id),
        'units_sold_by_month': get_units_sold_by_month(product_id),
        'revenue_by_month': get_revenue_by_month(product_id),
        'price_change_dates': get_price_change_dates(product_id),
        'price_history': get_price_history(product_id),
        'sales_by_day_of_week': get_sales_by_day_of_week(product_id, time_period)
    }
    
    return render_template('reports/fragments/_product_analytics_dashboard.html',
                         product=product,
                         analytics=analytics,
                         time_period=time_period)


@reports_bp.route('/products/<int:product_id>/stock_history')
@login_required
def product_stock_history(product_id):
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 10

        stock_query = StockLog.query.filter_by(product_id=product_id).order_by(StockLog.date.desc())
        paginated_logs = stock_query.paginate(page=page, per_page=per_page)

        # If it's an AJAX (HTMX) request, render only the table fragment
        if request.headers.get('HX-Request'):
            return render_template('reports/fragments/_product_stock_history.html',
                                   stock_history=paginated_logs.items,
                                   pagination=paginated_logs,
                                   product_id=product_id)

        # Else, render full page with the fragment inside
        return render_template('reports/product_stock_history_full.html',
                               stock_history=paginated_logs.items,
                               pagination=paginated_logs,
                               product_id=product_id)

    except Exception as e:
        logger.error(f"Error loading stock history: {str(e)}")
        return render_template('reports/product_stock_history_full.html',
                               stock_history=[],
                               error_message="Could not load stock history",
                               pagination=None,
                               product_id=product_id)




@reports_bp.route('/products/<int:product_id>/price_history')
@login_required
def product_price_history(product_id):
    price_history = PriceChange.query.filter_by(
        product_id=product_id
    ).order_by(
        PriceChange.changed_at.desc()
    ).limit(50).all()
    
    return render_template('reports/fragments/_product_price_history.html',
                        price_history=price_history)




@reports_bp.route('/products/<int:product_id>/sales_table')
@login_required
def product_sales_table(product_id):
    page = request.args.get('page', 1, type=int)
    per_page = 10
    time_period = request.args.get('time_period', 'month')

    try:
        product = Product.query.get(product_id)
        if not product:
            return render_template('reports/fragments/_product_sales_table.html',
                                   sales_records=[],
                                   product_id=product_id,
                                   page=page,
                                   total_pages=1,
                                   time_period=time_period,
                                   total_sales=0,
                                   error_message="Product not found")

        now = datetime.utcnow()
        if time_period == 'day':
            start_date = now - timedelta(days=1)
        elif time_period == 'week':
            start_date = now - timedelta(weeks=1)
        elif time_period == 'month':
            start_date = now - timedelta(days=30)
        elif time_period == 'year':
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=30)

        sales_query = db.session.query(
            Sale,
            CartItem.quantity,
            (CartItem.quantity * Product.selling_price).label('total_price'),
            Product.selling_price
        ).join(
            CartItem, and_(
                Sale.id == CartItem.sale_id,
                CartItem.product_id == product_id
            )
        ).join(
            Product, CartItem.product_id == Product.id
        ).filter(
            Sale.date >= start_date
        ).order_by(
            Sale.date.desc()
        )

        paginated_sales = sales_query.paginate(page=page, per_page=per_page)
        total_records = sales_query.count()

        sales_data = []
        for sale, quantity, total_price, unit_price in paginated_sales.items:
            sales_data.append({
                'sale_date': sale.date,
                'invoice_id': sale.id,
                'invoice_number': f"INV-{sale.id:05d}",
                'quantity': quantity,
                'unit_price': float(product.selling_price) if product else 0.0,
                'discount': 0.00,
                'total_price': float(total_price),
                'product_name': product.name if product else "N/A",
                'payment_method': sale.payment_method,        # 👈 Add this
                'customer_name': sale.customer_name or "-"    # 👈 Add this
            })



        return render_template('reports/fragments/_product_sales_table.html',
                               sales_records=sales_data,
                               product_id=product_id,
                               page=page,
                               total_pages=paginated_sales.pages,
                               time_period=time_period,
                               total_sales=total_records)

    except Exception as e:
        logger.exception("Error loading sales data")
        return render_template('reports/fragments/_product_sales_table.html',
                               sales_records=[],
                               product_id=product_id,
                               page=page,
                               total_pages=1,
                               time_period=time_period,
                               total_sales=0,
                               error_message="Could not load sales data")

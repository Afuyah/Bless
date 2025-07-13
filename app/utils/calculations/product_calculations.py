from flask import request, Blueprint, render_template, current_app, flash, redirect, url_for, jsonify
from datetime import datetime, timedelta
from collections import defaultdict, Counter, OrderedDict
import logging
import statistics
from math import ceil
from flask_login import login_required
from sqlalchemy import func, extract, and_, or_, case, distinct,  desc, text
from sqlalchemy.exc import SQLAlchemyError
from app import db, cache, csrf
from app.models import (Product, Sale, CartItem, PriceChange, StockLog, 
                       User,  Category)
from decimal import Decimal
from datetime import datetime, date, timedelta
from sqlalchemy import select
from app.utils.render import render_htmx
from sqlalchemy import func
from collections import Counter
from sqlalchemy.orm import joinedload
from werkzeug.exceptions import BadRequest
from sqlalchemy.exc import SQLAlchemyError, IntegrityError


import logging

logger = logging.getLogger(__name__)


from sqlalchemy import func, text

def get_month_label_expr(date_column):
    """Return a DB-compatible SQLAlchemy expression for 'YYYY-MM'."""
    if 'sqlite' in str(db.engine.url):
        return func.strftime('%Y-%m', date_column)
    return func.to_char(date_column, text("'YYYY-MM'"))




# Helper Functions
def get_time_filter(time_period, date_column=Sale.date):
    """Create SQL filter for the given time period"""
    periods = {
        'today': timedelta(days=1),
        'week': timedelta(weeks=1),
        'month': timedelta(days=30),
        'year': timedelta(days=365),
        'all': timedelta(days=365*10)  # 10 years as "all time"
    }
    return date_column >= (datetime.utcnow() - periods.get(time_period, timedelta(days=30)))

def safe_divide(numerator, denominator, default=0):
    """Safe division to avoid division by zero"""
    return numerator / denominator if denominator else default

# Basic Metrics
def calculate_total_revenue(product_id, time_period='month'):
    """Calculate total revenue for product in time period"""
    time_filter = get_time_filter(time_period)
    revenue = db.session.query(
        func.sum(CartItem.quantity * CartItem.unit_price)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        time_filter
    ).scalar()
    return float(revenue) if revenue else 0.0

def calculate_total_units_sold(product_id, time_period='month'):
    """Calculate total units sold for product"""
    time_filter = get_time_filter(time_period)
    units = db.session.query(
        func.sum(CartItem.quantity)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        time_filter
    ).scalar()
    return units or 0

def calculate_avg_profit_margin(product_id, time_period='month'):
    """Calculate average profit margin percentage"""
    time_filter = get_time_filter(time_period)
    margins = db.session.query(
        (Product.selling_price - Product.cost_price) / Product.selling_price * 100
    ).join(CartItem).join(Sale).filter(
        Product.id == product_id,
        time_filter,
        Product.selling_price > 0
    ).all()
    return round(statistics.mean([m[0] for m in margins]), 1) if margins else 0.0

# Trend Metrics
def calculate_revenue_trend(product_id, time_period):
    """Calculate revenue change vs previous period"""
    current = calculate_total_revenue(product_id, time_period)
    previous = calculate_total_revenue(product_id, f"previous_{time_period}")
    return round(safe_divide((current - previous), previous, 0) * 100, 1)

def calculate_sales_trend(product_id, time_period):
    """Calculate units sold change vs previous period"""
    current = calculate_total_units_sold(product_id, time_period)
    previous = calculate_total_units_sold(product_id, f"previous_{time_period}")
    return round(safe_divide((current - previous), previous, 0) * 100, 1)

def calculate_margin_trend(product_id, time_period):
    """Calculate profit margin change vs previous period"""
    current = calculate_avg_profit_margin(product_id, time_period)
    previous = calculate_avg_profit_margin(product_id, f"previous_{time_period}")
    return round(current - previous, 1)

# Sales Patterns
def get_peak_sales_day(product_id, time_period='month'):
    """Identify day of week with highest sales"""
    time_filter = get_time_filter(time_period)
    result = db.session.query(
        extract('dow', Sale.date).label('day_of_week'),
        func.sum(CartItem.quantity).label('total_units')
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        time_filter
    ).group_by('day_of_week').order_by(func.sum(CartItem.quantity).desc()).first()
    
    days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 
           'Thursday', 'Friday', 'Saturday']
    return days[int(result.day_of_week)] if result else "No sales data"

def get_avg_days_between_sales(product_id, time_period):
    sale_dates = db.session.query(Sale.date)\
        .join(CartItem)\
        .filter(CartItem.product_id == product_id)\
        .order_by(Sale.date.asc())\
        .all()

    # Convert to date objects safely
    parsed_dates = [
        d if isinstance(d, date) else datetime.strptime(d, '%Y-%m-%d').date()
        for d, in sale_dates
    ]

    if len(parsed_dates) < 2:
        return 0.0

    deltas = [
        (parsed_dates[i] - parsed_dates[i - 1]).days
        for i in range(1, len(parsed_dates))
    ]

    return round(statistics.mean(deltas), 1)


# Inventory Metrics
def get_max_stock_observed(product_id):
    """Get highest recorded stock level"""
    max_stock = db.session.query(
        func.max(StockLog.new_stock)
    ).filter_by(product_id=product_id).scalar()
    return max_stock or Product.query.get(product_id).stock

def get_stockout_count(product_id, time_period='month'):
    """Count how many times product went out of stock"""
    time_filter = get_time_filter(time_period, StockLog.date)
    return db.session.query(
        func.count(StockLog.id)
    ).filter_by(
        product_id=product_id,
        new_stock=0
    ).filter(time_filter).scalar() or 0

def get_avg_monthly_usage(product_id):
    """Calculate average monthly units sold"""
    monthly_data = db.session.query(
        extract('month', Sale.date),
        func.sum(CartItem.quantity)
    ).join(CartItem).filter(
        CartItem.product_id == product_id
    ).group_by(extract('month', Sale.date)).all()
    
    return round(statistics.mean([m[1] for m in monthly_data]), 1) if monthly_data else 0.0

def get_stock_cover_days(product_id):
    """Calculate how long current stock will last"""
    avg_monthly = get_avg_monthly_usage(product_id)
    current_stock = Product.query.get(product_id).stock
    return ceil(current_stock / (avg_monthly / 30)) if avg_monthly else 0

# Growth Metrics
def get_best_selling_month(product_id):
    """Identify month with highest historical sales"""
    result = db.session.query(
        extract('month', Sale.date),
        func.sum(CartItem.quantity)
    ).join(CartItem).filter(
        CartItem.product_id == product_id
    ).group_by(extract('month', Sale.date))\
     .order_by(func.sum(CartItem.quantity).desc()).first()
    
    months = ['January', 'February', 'March', 'April', 'May', 'June',
             'July', 'August', 'September', 'October', 'November', 'December']
    return months[int(result[0])-1] if result else "No data"

def get_revenue_growth(product_id, time_period='year'):
    """Year-over-year revenue growth percentage"""
    current_year = calculate_total_revenue(product_id, 'year')
    previous_year = calculate_total_revenue(product_id, 'previous_year')
    return round(safe_divide((current_year - previous_year), previous_year, 0) * 100, 1)

def get_sales_growth(product_id, time_period='year'):
    """Year-over-year units sold growth percentage"""
    current_year = calculate_total_units_sold(product_id, 'year')
    previous_year = calculate_total_units_sold(product_id, 'previous_year')
    return round(safe_divide((current_year - previous_year), previous_year, 0) * 100, 1)

# Pricing Metrics
def get_price_change_count(product_id, time_period='month'):
    """Count of price changes in period"""
    time_filter = get_time_filter(time_period, PriceChange.changed_at)
    return db.session.query(
        func.count(PriceChange.id)
    ).filter_by(
        product_id=product_id,
        change_type='price_update'
    ).filter(time_filter).scalar() or 0

def get_suggested_price(product_id):
    """Calculate optimal price based on cost and market"""
    product = Product.query.get(product_id)
    if not product or not product.cost_price:
        return 0.0
    
    avg_margin = db.session.query(
        func.avg((Product.selling_price - Product.cost_price) / Product.cost_price)
    ).filter(
        Product.category_id == product.category_id,
        Product.id != product_id
    ).scalar() or 0.3
    
    return round(float(product.cost_price) * (1 + float(avg_margin)), 2)

# Customer Behavior
def get_avg_quantity_per_order(product_id, time_period='month'):
    """Average units purchased per transaction"""
    time_filter = get_time_filter(time_period)
    avg = db.session.query(
        func.avg(CartItem.quantity)
    ).join(Sale).filter(
        CartItem.product_id == product_id,
        time_filter
    ).scalar()
    return round(avg, 1) if avg else 0.0

def get_repeat_purchase_rate(product_id, time_period='year'):
    """Simpler version using just customer names"""
    time_filter = get_time_filter(time_period)
    
    # Get all unique customer names who purchased this product
    customers = db.session.query(
        Sale.customer_name
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        Sale.customer_name.isnot(None),
        time_filter
    ).distinct().subquery()
    
    # Count customers who made repeat purchases
    repeaters = db.session.query(
        func.count(distinct(Sale.customer_name))
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        Sale.customer_name.in_(select([customers.c.customer_name])),
        time_filter
    ).scalar()
    
    # Count total unique customers
    total_customers = db.session.query(
        func.count(distinct(Sale.customer_name))
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        time_filter
    ).scalar()
    
    return round(safe_divide(repeaters, total_customers, 0) * 100, 1)


from sqlalchemy import func, text, desc

def get_analytics_months(product_id, limit=12):
    """Return the most recent N months where sales exist for a product."""
    # Determine if SQLite is being used
    if 'sqlite' in str(db.engine.url):
        # SQLite uses strftime
        month_label = func.strftime('%Y-%m', Sale.date).label('month')
    else:
        # PostgreSQL uses to_char
        month_label = func.to_char(Sale.date, text("'YYYY-MM'")).label('month')

    return [
        row[0]
        for row in db.session.query(month_label)
        .join(CartItem)
        .filter(CartItem.product_id == product_id)
        .group_by(month_label)
        .order_by(desc('month'))
        .limit(limit)
        .all()
    ]

def get_units_sold_by_month(product_id, months=None):
    """Get total units sold for a product per month."""
    if months is None:
        months = get_analytics_months(product_id)

    month_expr = get_month_label_expr(Sale.date)

    results = []
    for month in months:
        total = db.session.query(
            func.sum(CartItem.quantity)
        ).join(Sale).filter(
            CartItem.product_id == product_id,
            month_expr == month
        ).scalar() or 0
        results.append(total)

    return results


def get_revenue_by_month(product_id):
    """Get total revenue (quantity * unit price) per month for a product."""
    months = get_analytics_months(product_id)
    month_expr = get_month_label_expr(Sale.date)

    return [
        float(
            db.session.query(
                func.sum(CartItem.quantity * CartItem.unit_price)
            )
            .join(Sale)
            .filter(
                CartItem.product_id == product_id,
                month_expr == month
            )
            .scalar() or 0
        )
        for month in months
    ]


def get_price_history(product_id):
    """Returns historical selling prices for a product."""
    rows = db.session.query(PriceChange.new_price).filter_by(
        product_id=product_id
    ).order_by(PriceChange.changed_at).all()

    return [float(row[0]) for row in rows]

def get_price_change_dates(product_id, limit=12):
    """Get price change dates for a product."""
    try:
        changes = PriceChange.query.filter_by(
            product_id=product_id,
            change_type='selling_price_update'
        ).order_by(PriceChange.changed_at.desc()).limit(limit).all()

        return [
            c.changed_at.strftime('%Y-%m-%d')
            for c in reversed(changes)
        ] if changes else []

    except Exception as e:
        db.session.rollback()
        logger.error(
            f"Error getting price change dates for product {product_id}: {e}",
            exc_info=True
        )
        return []

def get_sales_by_day_of_week(product_id, time_period='month'):
    """Sales distribution by weekday"""
    time_filter = get_time_filter(time_period)
    results = db.session.query(
        extract('dow', Sale.date),
        func.sum(CartItem.quantity)
    ).join(CartItem).filter(
        CartItem.product_id == product_id,
        time_filter
    ).group_by(extract('dow', Sale.date)).all()
    
    day_map = {int(day): units for day, units in results}
    return [day_map.get(i, 0) for i in range(7)]  # Sunday=0 to Saturday=6




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

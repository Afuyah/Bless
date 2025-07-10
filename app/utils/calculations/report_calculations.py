
import logging
import statistics
from math import ceil
from flask_login import login_required
from sqlalchemy import func, extract, and_, or_, case, Date
from sqlalchemy.exc import SQLAlchemyError
from app import db, cache, csrf
from app.models import (Product, Sale, CartItem, PriceChange, StockLog, 
                       User,  Category)
from decimal import Decimal
from datetime import datetime, date
from sqlalchemy import select
from app.utils.render import render_htmx
from sqlalchemy import func
from collections import Counter
from sqlalchemy.orm import joinedload
from werkzeug.exceptions import BadRequest
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from app.utils.calculations.product_calculations import *




# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)



def generate_daily_report_data(shop_id, report_date):
    try:
        # Initialize all data structures
        product_sales = defaultdict(lambda: {'quantity': 0, 'revenue': Decimal('0.0')})
        payment_methods = defaultdict(Decimal)
        hourly_sales = defaultdict(Decimal)
        staff_performance = defaultdict(lambda: {'sales': 0, 'amount': Decimal('0.0')})
        complete_product_sales = defaultdict(lambda: {'quantity': 0, 'revenue': Decimal('0.0')})

        # Base sales query - now shop-scoped
        sales = Sale.query.filter(
            func.date(Sale.date) == report_date,
            Sale.shop_id == shop_id
        ).options(
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

        # Process sales data
        for sale in sales:
            method = sale.payment_method.lower()
            payment_methods[method] += Decimal(str(sale.total))

            hour = sale.date.hour
            hourly_sales[f"{hour}:00-{hour+1}:00"] += Decimal(str(sale.total))

            if sale.user:
                staff_performance[sale.user.username]['sales'] += 1
                staff_performance[sale.user.username]['amount'] += Decimal(str(sale.total))

            for item in sale.cart_items:
                product_name = item.product.name
                quantity = item.quantity
                revenue = Decimal(str(item.total_price))

                complete_product_sales[product_name]['quantity'] += quantity
                complete_product_sales[product_name]['revenue'] += revenue
                product_sales[product_name]['quantity'] += quantity
                product_sales[product_name]['revenue'] += revenue

        # Summarize
        total_sales = sum(Decimal(str(sale.total)) for sale in sales)
        total_transactions = len(sales)
        total_profit = sum(Decimal(str(sale.profit)) if sale.profit is not None else Decimal('0') for sale in sales)
        avg_sale = total_sales / Decimal(str(total_transactions)) if total_transactions else Decimal('0')

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
        current_app.logger.error(f"Error generating daily report for shop {shop_id}: {str(e)}")
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

#weekly report analysis
def generate_weekly_report_context(shop_id, week, start_date, end_date):
    sales = Sale.query.filter(
        Sale.shop_id == shop_id,
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
        .filter(
            Sale.shop_id == shop_id,
            Sale.date >= prev_week_start,
            Sale.date <= prev_week_end
        )
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


    #mothly reports
  
class MonthlySalesAnalyzer:
    """Helper class to encapsulate monthly sales analytics logic"""
    
    def __init__(self, shop_id, month_str=None):
        self.shop_id = shop_id
        self.month_str = month_str or datetime.utcnow().strftime('%Y-%m')
        self.report_month = None
        self.first_day = None
        self.last_day = None
        self.prev_month = None
        self.next_month = None
        self.days_in_month = None
        self.sales = []
        self.metrics = {}  # Store metrics for later access

        
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
                    Sale.shop_id == self.shop_id,
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
            self.metrics = metrics
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

        metrics['total_cost'] = total_cost
        metrics['avg_sale'] = metrics['total_sales'] / metrics['total_transactions'] if metrics['total_transactions'] > 0 else Decimal('0.0')
        metrics['refund_rate'] = (Decimal(refund_count) / metrics['total_transactions'] * 100) if metrics['total_transactions'] > 0 else Decimal('0.0')

        if metrics['total_sales'] > 0:
            gross_profit = metrics['total_sales'] - total_cost
            metrics['avg_profit_margin'] = (gross_profit / metrics['total_sales'] * 100)
        else:
            metrics['avg_profit_margin'] = Decimal('0.0')

        self.metrics = metrics  # ✅ Save for comparison use
        return {k: float(v) if isinstance(v, Decimal) else v for k, v in metrics.items()}

    
    def calculate_comparisons(self):
        comparisons = {
            'mom_sales': Decimal('0.0'),
            'mom_change': Decimal('0.0'),
            'yoy_sales': Decimal('0.0'),
            'yoy_change': Decimal('0.0'),
            'mom_profit': Decimal('0.0'),
            'yoy_profit': Decimal('0.0')
        }

        # Month-over-month
        prev_last = (self.prev_month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        prev_data = db.session.query(
            func.sum(Sale.total), func.sum(Sale.profit)
        ).filter(
            Sale.shop_id == self.shop_id,  # ✅ Scoped
            Sale.date >= self.prev_month,
            Sale.date <= prev_last
        ).first()

        prev_total, prev_profit = prev_data or (0, 0)
        prev_sales = Decimal(str(prev_total or 0))
        prev_profit = Decimal(str(prev_profit or 0))

        comparisons['mom_sales'] = prev_sales
        comparisons['mom_profit'] = prev_profit

        if prev_sales > 0:
            comparisons['mom_change'] = (Decimal(str(self.metrics['total_sales'])) - prev_sales) / prev_sales * 100

        # Year-over-year
        last_year = self.first_day - timedelta(days=365)
        last_year_end = (last_year + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        ly_data = db.session.query(
            func.sum(Sale.total), func.sum(Sale.profit)
        ).filter(
            Sale.shop_id == self.shop_id,  # ✅ Scoped
            Sale.date >= last_year.replace(day=1),
            Sale.date <= last_year_end
        ).first()

        ly_sales = Decimal(str(ly_data[0] or 0))
        ly_profit = Decimal(str(ly_data[1] or 0))

        comparisons['yoy_sales'] = ly_sales
        comparisons['yoy_profit'] = ly_profit

        if ly_sales > 0:
            comparisons['yoy_change'] = (Decimal(str(self.metrics['total_sales'])) - ly_sales) / ly_sales * 100

        return {k: float(v) if isinstance(v, Decimal) else v for k, v in comparisons.items()}

    def generate_context(self, full_report=True):
        """Main method to return analytics context (HTMX or full view)"""
        if not self.initialize_dates():
            raise ValueError("Invalid month format")

        if not self.fetch_sales_data():
            raise RuntimeError("Failed to fetch sales")

        core = self.calculate_core_metrics()
        comparisons = self.calculate_comparisons()
        time = self.generate_time_analytics() if full_report else {}
        products = self.generate_product_analytics() if full_report else {}

        return {
            'month': self.month_str,
            'date_range': f"{self.first_day.strftime('%B %Y')}",
            'calendar': {
                'prev': self.prev_month.strftime('%Y-%m'),
                'next': self.next_month.strftime('%Y-%m'),
                'current': datetime.today().strftime('%Y-%m')
            },
            'core_metrics': core,
            'comparisons': comparisons,
            'time_analytics': time,
            'product_analytics': products
        }


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


    def generate_payment_analysis(self):
        """Generate analytics summary by payment method"""
        payment_summary = defaultdict(lambda: {
            'total': Decimal('0.0'),
            'count': 0
        })

        for sale in self.sales:
            method = sale.payment_method or 'Unknown'
            payment_summary[method]['total'] += Decimal(str(sale.total))
            payment_summary[method]['count'] += 1

        # Convert to float for JSON
        return {
            method: {
                'total': float(data['total']),
                'count': data['count']
            } for method, data in payment_summary.items()
        }
               
               
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
            'shop_id': self.shop_id,
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
from flask_login import current_user
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional
from flask import request, session
from .. import db, socketio
from .repositories import ProductRepository, CategoryRepository, SaleRepository, RegisterSessionRepository
from ..models import Shop, Sale, CartItem, Category, Product, RegisterSession, Tax
from sqlalchemy.sql import bindparam
from app.utils.pricing import PricingUtil
import threading
from sqlalchemy.orm import joinedload, with_loader_criteria
from app.utils.time import get_kenya_today_range
from sqlalchemy import and_, func, case
import logging

import logging
import traceback
from functools import lru_cache




logger = logging.getLogger(__name__)


def run_checkout_tasks(sale_id: int, shop_id: int, user_id: int, total: float, item_count: int):
    try:
        # Generate receipt (safe access)
        receipt = ReceiptService.generate(sale_id)
        logger.info("Receipt generated successfully")

        
        # Emit real-time update
        socketio.emit('sale_completed', {
            'sale_id': sale_id,
            'shop_id': shop_id,
            'total': total,
            'items_count': item_count,
        }, room=f'pos_{shop_id}')

    except Exception as e:
        logger.error("Post-checkout task failed", extra={'sale_id': sale_id, 'error': str(e), 'trace': traceback.format_exc()})


# In services.py
class SalesService:
    @staticmethod
    def get_pos_data(shop_id: int) -> Dict:
        """
        Get all data needed to initialize the POS interface
        """
        try:
            shop = Shop.query.get_or_404(shop_id)

            return {
                'shop': {
                    'id': shop.id,
                    'name': shop.name,
                    'currency': shop.currency,
                    'logo_url': shop.logo_url
                },
                'categories': CategoryService.get_for_pos(shop_id),
                'products': [
                    p.serialize(for_pos=True)
                    for p in ProductRepository.get_available_for_sale(shop_id)
                ],
                'payment_methods': PaymentService.get_available_methods(shop_id),
                'tax_rates': TaxService.get_rates(shop_id)
                
            }
        except Exception as e:
            logger.error(f"Error getting POS data: {str(e)}", exc_info=True)
            raise ValueError("Failed to load POS data") from e

    
    @staticmethod
    def process_checkout(
        shop_id: int,
        user_id: int,
        cart_items: List[Dict],
        payment_method: str,
        customer_data: Optional[Dict] = None
    ) -> Dict:
        """
        Ultra-optimized sale transaction processing with minimal latency and safe commit flow.
        """

        if not cart_items:
            raise ValueError("Cannot process empty sale")
        if not payment_method:
            raise ValueError("Payment method required")

        cart_items = [{'product_id': int(item['product_id']), 'quantity': int(item['quantity'])}
                      for item in cart_items]

        try:
            product_ids = [item['product_id'] for item in cart_items]
            products, register_session = ProductRepository.get_bulk_for_sale_and_session(product_ids, shop_id)
            if not register_session:
                raise ValueError("No open register session")

            product_map = {p.id: p for p in products}

            subtotal = Decimal('0')
            total_cost = Decimal('0')
            cart_item_data = []
            stock_updates = []

            tax_rate = Decimal(str(Tax.get_tax_rate(shop_id)))

            for item in cart_items:
                product = product_map.get(item['product_id'])
                if not product:
                    raise ValueError(f"Product {item['product_id']} not found")
                quantity = item['quantity']
                if product.stock < quantity:
                    raise ValueError(f"Insufficient stock for {product.name}")

                item_subtotal = (
                    (quantity // product.combination_size * product.combination_price +
                     min(quantity % product.combination_size * product.selling_price, product.combination_price))
                    if product.is_combo and product.combination_size > 1
                    else quantity * product.selling_price
                )
                item_cost = quantity * product.cost_price

                subtotal += Decimal(str(item_subtotal))
                total_cost += Decimal(str(item_cost))

                cart_item_data.append({
                    'shop_id': shop_id,
                    'product_id': product.id,
                    'quantity': quantity,
                    'unit_price': float(product.selling_price),
                    'total_price': float(item_subtotal)
                })
                stock_updates.append({'p_id': product.id, 'new_stock': product.stock - quantity})

            tax_amount = subtotal * tax_rate
            total = subtotal + tax_amount

            sale = Sale(
                shop_id=shop_id,
                user_id=user_id,
                register_session_id=register_session.id,
                subtotal=float(subtotal),
                tax=float(tax_amount),
                total=float(total),
                payment_method=payment_method,
                customer_name=str(customer_data.get('name', '')).strip()[:100] if customer_data else None,
                customer_phone=str(customer_data.get('phone', '')).strip()[:20] if customer_data else None,
                profit=float(subtotal - total_cost)
            )
            db.session.add(sale)
            db.session.flush()  # Get sale.id

            if cart_item_data:
                db.session.execute(
                    CartItem.__table__.insert(),
                    [dict(item, sale_id=sale.id) for item in cart_item_data]
                )

            if stock_updates:
                db.session.execute(
                    Product.__table__.update()
                    .where(Product.id == bindparam('p_id'))
                    .values(stock=bindparam('new_stock')),
                    stock_updates
                )

            db.session.commit()

            # Launch background thread
            threading.Thread(
                target=run_checkout_tasks,
                args=(sale.id, shop_id, user_id, float(total), len(cart_items)),
                daemon=True
            ).start()

            return {
                'success': True,
                'sale_id': sale.id,
                'amount_paid': float(total),
                'change_due': 0.0,
                'receipt': None,  
                'receipt_pending': True
            }

        except Exception as e:
            db.session.rollback()
            logger.error("Checkout failed", extra={
                'shop_id': shop_id,
                'error': str(e),
                'trace': traceback.format_exc()
            })
            raise ValueError(f"Checkout processing failed: {str(e)}")


    @staticmethod
    def get_recent_transactions(shop_id: int):
        return Sale.query.filter_by(shop_id=shop_id).order_by(Sale.date.desc()).limit(10).all()

    @staticmethod
    def get_transactions(shop_id: int, page=1, per_page=20, date_from=None, date_to=None):
        query = Sale.query.filter(Sale.shop_id == shop_id)
        if date_from:
            query = query.filter(Sale.date >= date_from)
        if date_to:
            query = query.filter(Sale.date <= date_to)
        return query.order_by(Sale.date.desc()).paginate(page=page, per_page=per_page)

    @staticmethod
    def calculate_expected_cash(shop_id, session_id):
        from app.models import Sale
        from sqlalchemy import func

        result = db.session.query(
            func.coalesce(func.sum(Sale.total), 0)
        ).filter(
            Sale.shop_id == shop_id,
            Sale.register_session_id == session_id,
            Sale.is_deleted == False
        ).scalar()

        return round(float(result or 0), 2)


    @staticmethod
    def get_register_summary(shop_id, session_id):
        sales = db.session.query(
            func.coalesce(func.sum(Sale.total), 0).label('total'),
            func.count(Sale.id).label('count'),
            func.coalesce(func.sum(case(
                [(Sale.payment_method == 'cash', Sale.total)],
                else_=0
            )), 0).label('cash'),
            func.coalesce(func.sum(case(
                [(Sale.payment_method == 'mpesa', Sale.total)],
                else_=0
            )), 0).label('mpesa')
        ).filter(
            Sale.shop_id == shop_id,
            Sale.register_session_id == session_id,
            Sale.is_deleted == False
        ).first()

        return {
            'total': float(sales.total or 0),
            'count': sales.count,
            'cash': float(sales.cash or 0),
            'mpesa': float(sales.mpesa or 0)
        }


     

class ReceiptService:
    @staticmethod
    def generate(sale_id: int, format: str = 'json') -> Dict:
        """Generate receipt data using CartItem as sale items"""
        sale = Sale.query.get_or_404(sale_id)
        items = CartItem.query.filter_by(sale_id=sale_id).join(Product).all()
        
        receipt_data = {
            'id': sale.id,
            'date': sale.date.strftime('%Y-%m-%d %H:%M'),
            'shop': {
                'name': sale.shop.name,
                'location': sale.shop.location,
                'phone': sale.shop.phone,
                'tax_id': sale.shop.taxes[0].id if sale.shop.taxes else None

            },
            'items': [{
                'name': item.product.name,
                'quantity': item.quantity,
                'unit_price': item.product.selling_price,  # Current price at time of sale
                'total': item.quantity * item.product.selling_price
            } for item in items],
            'subtotal': sale.subtotal,
            'tax': sale.tax,
            'total': sale.total,
            'payment_method': sale.payment_method,
            'cashier': sale.user.username if sale.user else 'System',
            'customer': {
                'name': sale.customer_name,
                'phone': sale.customer_phone
            } if sale.customer_name else None
        }
        
        # Add barcode/QR code for receipt tracking
        receipt_data['barcode'] = f"RECEIPT-{sale.id}-{sale.date.strftime('%Y%m%d')}"
        
        return receipt_data


class ProductService:
    @staticmethod
    def search(shop_id: int, query: str, category_id: Optional[int] = None, limit: Optional[int] = None) -> List[Dict]:
        """
        Search products with optional limit, error handling, and result formatting.
        """
        try:
            results = ProductRepository.search_available(
                shop_id=shop_id,
                query=query,
                category_id=category_id,
                limit=limit  # 👈 pass to repository layer
            )

            return [{
                'id': p.id,
                'name': p.name,
                'price': float(p.selling_price),
                'image': p.image_url or '/static/images/product-placeholder.png',
                'category': p.category.name,
                'category_id': p.category.id,
                'stock': p.stock,
                'barcode': p.barcode or '',
                'is_combo': bool(p.combination_size and p.combination_size > 1),
                'combination_price': float(p.combination_price) if p.combination_price and p.combination_size and p.combination_size > 1 else None,
                'combination_size': p.combination_size if p.combination_size and p.combination_size > 1 else None,
            } for p in results]

        except Exception as e:
            logger.error(f"Product search failed for shop {shop_id}: {str(e)}")
            return []

    @staticmethod
    def get_available_for_sale(shop_id: int) -> List[Dict]:
        """
        Get all available products for a shop with inventory status
        """
        try:
            products = ProductRepository.get_available_for_sale(shop_id)
            return [{
                'id': p.id,
                'name': p.name,
                'price': float(p.selling_price),
                'image': p.image_url or '/static/images/product-placeholder.png',
                'category': p.category.name,
                'category_id': p.category.id,
                'stock': p.stock,
                'is_low_stock': p.stock < 10,
                'is_combo': bool(p.combination_size and p.combination_size > 1),
                'combination_price': float(p.combination_price) if p.combination_price and p.combination_size and p.combination_size > 1 else None,
                'combination_size': p.combination_size if p.combination_size and p.combination_size > 1 else None,

            } for p in products]

        except Exception as e:
            logger.error(f"Failed to get products for shop {shop_id}: {str(e)}")
            return []



class CategoryService:
    @staticmethod
    def get_for_pos(shop_id: int) -> List[Dict]:
        """
        Return serialized category list with their valid products for POS display.
        """
        categories = CategoryRepository.get_for_pos(shop_id)

        return [
            {
                'id': c.id,
                'name': c.name,
                'products': sorted([
                    {
                        'id': p.id,
                        'name': p.name,
                        'price': float(p.selling_price),
                        'image_url': p.image_url or '/static/images/product-placeholder.png',
                        'stock': p.stock,
                        'barcode': p.barcode,
                        'category_id': p.category_id,
                        'is_combo': bool(p.combination_size and p.combination_size > 1),
                        'combination_price': float(p.combination_price) if p.combination_price and p.combination_size and p.combination_size > 1 else None,
                        'combination_size': p.combination_size if p.combination_size and p.combination_size > 1 else None,
                    }
                    for p in c.products
                    if p.is_active and p.stock > 0
                ], key=lambda x: x['name'])
            }
            for c in categories
        ]



    @staticmethod
    def get_ranked(shop_id: int) -> List[Dict]:
        """Get top selling categories"""
        categories = CategoryRepository.get_ranked_categories(shop_id)
        return [{
            'id': c.id,
            'name': c.name,
            'sales_count': len(c.products)
        } for c in categories]


class PaymentService:
    @staticmethod
    def get_available_methods(shop_id: int) -> List[Dict]:
        """Get payment methods enabled for this shop"""
        # In real implementation, this would come from shop settings
        return [
            {'code': 'cash', 'name': 'Cash', 'needs_confirmation': False},
            {'code': 'card', 'name': 'Card', 'needs_confirmation': True},
            {'code': 'transfer', 'name': 'Bank Transfer', 'needs_confirmation': True}
        ]


class TaxService:
    @staticmethod
    def calculate_tax(subtotal: float, shop_id: int) -> float:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        if not tax:
            return 0.0
        return round(subtotal * tax.rate, 2)

    @staticmethod
    def get_rates(shop_id: int) -> List[Dict]:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        if not tax:
            return []
        return [{
            'name': tax.name,
            'rate': tax.rate,
            'inclusive': False,
            'description': tax.description,
            'kra_code': tax.kra_code
        }]

    @staticmethod
    @lru_cache(maxsize=32)
    def get_tax_rate(shop_id: int) -> float:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        return float(tax.rate if tax else 0.0)



class SalesSummaryService:
    @staticmethod
    def get_summary(shop_id: int, session_id: Optional[int] = None) -> Dict:
        """
        Return sales summary and recent sales for a shop.
        If session_id is provided, the summary will be scoped to that session.
        Otherwise, it defaults to today's date summary.
        """
        try:
            filters = [
                Sale.shop_id == shop_id,
                Sale.is_deleted == False
            ]

            # Determine filter context: by session OR today
            if session_id:
                filters.append(Sale.register_session_id == session_id)
            else:
                date_from, date_to = get_kenya_today_range()
                filters.append(Sale.date >= date_from)
                filters.append(Sale.date <= date_to)

            # Summary stats
            summary = (
                db.session.query(
                    func.count(Sale.id).label("sales_count"),
                    func.sum(Sale.total).label("total_sales"),
                    func.sum(Sale.tax).label("total_tax"),
                    func.sum(Sale.profit).label("total_profit")
                )
                .filter(*filters)
                .first()
            )

            # Payment breakdown
            payment_data = (
                db.session.query(
                    Sale.payment_method,
                    func.sum(Sale.total).label("amount")
                )
                .filter(*filters)
                .group_by(Sale.payment_method)
                .all()
            )

            payment_methods = {
                method: float(amount or 0) for method, amount in payment_data
            }

            # Recent sales (limit to 5, same filter scope)
            recent_sales = (
                Sale.query
                .filter(*filters)
                .order_by(Sale.date.desc())
                .limit(5)
                .all()
            )

            return {
                'success': True,
                'data': {
                    'summary': {
                        'sales_count': summary.sales_count or 0,
                        'total_sales': float(summary.total_sales or 0),
                        'total_tax': float(summary.total_tax or 0),
                        'total_profit': float(summary.total_profit or 0),
                        'payment_methods': payment_methods
                    },
                    'recent_sales': [
                        {
                            'id': s.id,
                            'total': float(s.total),
                            'date': s.date.strftime('%Y-%m-%d %H:%M'),
                            'payment_method': s.payment_method,
                            'customer': s.customer_name or 'Walk-in',
                            'cashier': s.user.username if s.user else 'N/A',
                            'register_session_id': s.register_session_id
                        } for s in recent_sales
                    ]
                }
            }

        except Exception as e:
            return {
                'success': False,
                'message': f"Failed to generate summary: {str(e)}"
            }


class RegisterService:

    @staticmethod
    def open_register(shop_id: int, user_id: int, opening_cash: float) -> RegisterSession:
        """
        Open a new register session after ensuring no session is currently open.
        """
        if RegisterSessionRepository.get_open_session(shop_id):
            raise ValueError("A register is already open for this shop.")
        
        return RegisterSessionRepository.create(
            shop_id=shop_id,
            user_id=user_id,
            opening_cash=opening_cash
        )

    @staticmethod
    def close_register(
        shop_id: int,
        user_id: int,
        session_id: int,
        closing_cash: float,
        notes: Optional[str] = None
    ) -> RegisterSession:
        """
        Close an open register session after validating session ownership and expected cash.
        """
        open_session = RegisterSessionRepository.get_open_session(shop_id)


        if not open_session:
            raise ValueError("No open register session found.")
        
        if open_session.id != session_id:
            raise ValueError("Session mismatch. Cannot close a session not currently open.")

        expected_cash = RegisterService._calculate_expected_cash(shop_id, session_id)

        return RegisterSessionRepository.close(
            session_id=session_id,
            user_id=user_id,
            closing_cash=closing_cash,
            expected_cash=expected_cash,
            notes=notes
        )

    @staticmethod
    def get_summary(shop_id: int, session_id: int) -> Dict:
        """
        Return detailed summary of a register session including payment breakdown.
        """
        session = RegisterSessionRepository.get_by_id(session_id)
        if not session or session.shop_id != shop_id:
            raise ValueError("Invalid register session.")

        # Aggregate sales per payment method
        result = db.session.query(
            func.coalesce(func.sum(Sale.total), 0).label("total_sales"),
            func.coalesce(func.sum(case((Sale.payment_method == 'cash', Sale.total), else_=0)), 0).label("cash"),
            func.coalesce(func.sum(case((Sale.payment_method == 'mpesa', Sale.total), else_=0)), 0).label("mpesa"),
            func.coalesce(func.sum(case((Sale.payment_method == 'card', Sale.total), else_=0)), 0).label("card"),
            func.coalesce(func.sum(case(
                (Sale.payment_method.notin_(['cash', 'mpesa', 'card']), Sale.total),
                else_=0
            )), 0).label("other"),
            func.count(Sale.id).label("sale_count")
        ).filter(
            Sale.shop_id == shop_id,
            Sale.register_session_id == session_id,
            Sale.is_deleted == False
        ).first()

        opening_cash = float(session.opening_cash or 0)
        cash_sales = float(result.cash or 0)
        expected_cash = round(opening_cash + cash_sales, 2)

        return {
            "session_id": session.id,
            "opened_at": session.opened_at.strftime('%Y-%m-%d %H:%M'),
            "opened_by": {
                "id": session.opened_by.id,
                "username": session.opened_by.username
            } if session.opened_by else None,
            "opening_cash": opening_cash,
            "total_sales": float(result.total_sales or 0),
            "expected_cash": expected_cash,
            "payment_methods": {
                "cash": round(float(result.cash or 0), 2),
                "mpesa": round(float(result.mpesa or 0), 2),
                "card": round(float(result.card or 0), 2),
                "other": round(float(result.other or 0), 2),
            },
            "sale_count": result.sale_count,
            "is_open": session.closed_at is None
        }

    @staticmethod
    def _calculate_expected_cash(shop_id: int, session_id: int) -> float:
        """
        Internal helper to compute expected cash (opening + cash sales) for a session.
        """
        session = RegisterSessionRepository.get_by_id(session_id)
        if not session or session.shop_id != shop_id:
            raise ValueError("Session not found or does not belong to this shop.")

        cash_sales = db.session.query(
            func.coalesce(func.sum(Sale.total), 0)
        ).filter(
            Sale.shop_id == shop_id,
            Sale.register_session_id == session_id,
            Sale.payment_method == 'cash',
            Sale.is_deleted == False
        ).scalar()

        return round(float(session.opening_cash) + float(cash_sales or 0), 2)


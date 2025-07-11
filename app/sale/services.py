from flask_login import current_user
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional
from flask import request, session
from .. import db, socketio
from .repositories import ProductRepository, CategoryRepository, SaleRepository, RegisterSessionRepository
from ..models import Shop, Sale, CartItem, Category, Product, RegisterSession

from app.utils.pricing import PricingUtil

from sqlalchemy.orm import joinedload, with_loader_criteria
from app.utils.time import get_kenya_today_range
from sqlalchemy import and_, func, case
import logging

logger = logging.getLogger(__name__)

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
                'tax_rates': TaxService.get_rates(shop_id),
                'current_cart': CartService.get(shop_id, current_user.id)
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
        Complete the sale transaction with full validation and session tracking
        """
        if not cart_items:
            raise ValueError("Cannot process empty sale")

        try:
            validated_items = []
            for item in cart_items:
                product = ProductRepository.get_for_sale(item['product_id'], shop_id)
                if not product:
                    raise ValueError(f"Product {item['product_id']} not found in shop")
                if product.stock < item['quantity']:
                    raise ValueError(
                        f"Insufficient stock for {product.name}. "
                        f"Available: {product.stock}, Requested: {item['quantity']}"
                    )

                subtotal = PricingUtil.calculate_combination_price(product, item['quantity'])
                cost = float(product.cost_price) * item['quantity']

                validated_items.append({
                    'product_id': product.id,
                    'quantity': item['quantity'],
                    'price': float(product.selling_price),  # keep for UI/reference
                    'cost_price': float(product.cost_price),
                    'name': product.name,
                    'subtotal': subtotal,
                    'total_cost': cost
                })

            # Financials
            subtotal = sum(Decimal(str(item['subtotal'])) for item in validated_items)
            total_cost = sum(Decimal(str(item['total_cost'])) for item in validated_items)
            tax_amount = TaxService.calculate_tax(float(subtotal), shop_id)
            total = subtotal + Decimal(str(tax_amount))

            # Ensure register session is open
            register_session = RegisterSession.query.filter_by(
                shop_id=shop_id,
                closed_at=None,
                is_deleted=False
            ).first()

            if not register_session:
                raise ValueError("No open register session. Please open the register first.")

            # Create Sale record
            sale = Sale(
                shop_id=shop_id,
                user_id=user_id,
                register_session_id=register_session.id,
                subtotal=float(subtotal),
                tax=float(tax_amount),
                total=float(total),
                payment_method=payment_method,
                customer_name=customer_data.get('name'),
                customer_phone=customer_data.get('phone'),
                profit=float(subtotal - total_cost)  # Net profit before tax
            )
            db.session.add(sale)
            db.session.flush()

            # Save cart items
            for item in validated_items:
                cart_item = CartItem(
                    shop_id=shop_id,
                    product_id=item['product_id'],
                    quantity=item['quantity'],
                    sale_id=sale.id,
                    unit_price=item['price'],
                    total_price=item['subtotal']  # ← combo-based subtotal
                )
                db.session.add(cart_item)

                # Reduce stock
                product = Product.query.get(item['product_id'])
                product.stock -= item['quantity']
                db.session.add(product)

            # Generate receipt
            receipt = ReceiptService.generate(sale.id)

            # Clear cart
            CartService.clear(shop_id, user_id)

            # Emit real-time event
            socketio.emit('sale_completed', {
                'sale_id': sale.id,
                'shop_id': shop_id,
                'total': float(total),
                'items_count': len(validated_items),
                'timestamp': datetime.utcnow().isoformat()
            }, room=f'pos_{shop_id}')

            db.session.commit()

            return {
                'success': True,
                'sale_id': sale.id,
                'receipt': receipt,
                'amount_paid': float(total),
                'change_due': 0.0
            }

        except Exception as e:
            db.session.rollback()
            logger.error(f"Checkout failed for shop {shop_id}: {str(e)}", exc_info=True)
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


class CartService:
    @staticmethod
    def get(shop_id: int, user_id: int) -> List[Dict]:
        """Get current cart contents with product validation"""
        cart_key = f'cart_{shop_id}_{user_id}'
        cart = session.get(cart_key, [])

        valid_items = []
        for item in cart:
            product = ProductRepository.get_for_sale(item['product_id'], shop_id)
            if product:
                valid_items.append({
                    'product_id': product.id,
                    'quantity': item['quantity'],
                    'price': float(product.selling_price),
                    'name': product.name,
                    'image': product.image_url,
                    'subtotal': PricingUtil.calculate_combination_price(product, item['quantity'])
                })

        if len(valid_items) != len(cart):
            session[cart_key] = valid_items
            session.modified = True

        return valid_items


    @staticmethod
    def add_item(shop_id: int, user_id: int, product_id: int, quantity: int = 1) -> Dict:
        """Add product to cart with validation"""
        product = ProductRepository.get_for_sale(product_id, shop_id)
        if not product:
            raise ValueError("Product not available for sale")

        cart_key = f'cart_{shop_id}_{user_id}'
        cart = session.get(cart_key, [])

        existing_item = next((item for item in cart if item['product_id'] == product_id), None)

        if existing_item:
            existing_item['quantity'] += quantity
        else:
            cart.append({
                'product_id': product_id,
                'quantity': quantity,
                'price': float(product.selling_price),  # keep for UI
                'name': product.name,
                'image': product.image_url
            })

        # Recalculate subtotal using combo logic
        for item in cart:
            product = ProductRepository.get_for_sale(item['product_id'], shop_id)
            item['subtotal'] = PricingUtil.calculate_combination_price(product, item['quantity'])

        session[cart_key] = cart
        session.modified = True

        return {
            'success': True,
            'cart': cart,
            'cart_count': sum(item['quantity'] for item in cart),
            'cart_total': sum(item['subtotal'] for item in cart)
        }



    @staticmethod
    def update_quantity(shop_id: int, user_id: int, product_id: int, new_quantity: int) -> Dict:
        """Update product quantity in cart"""
        if new_quantity <= 0:
            raise ValueError("Quantity must be positive")

        cart_key = f'cart_{shop_id}_{user_id}'
        cart = session.get(cart_key, [])

        item = next((i for i in cart if i['product_id'] == product_id), None)
        if not item:
            raise ValueError("Product not in cart")

        item['quantity'] = new_quantity

        product = ProductRepository.get_for_sale(product_id, shop_id)
        item['subtotal'] = PricingUtil.calculate_combination_price(product, new_quantity)

        session[cart_key] = cart
        session.modified = True

        return {
            'success': True,
            'cart_count': sum(i['quantity'] for i in cart),
            'cart_total': sum(i['subtotal'] for i in cart)
        }


    @staticmethod
    def clear(shop_id: int, user_id: int) -> None:
        """Empty the cart completely"""
        cart_key = f'cart_{shop_id}_{user_id}'
        if cart_key in session:
            del session[cart_key]
            session.modified = True
    @staticmethod
    def remove_item(shop_id: int, user_id: int, product_id: int) -> Dict:
        """Remove a product from the cart"""
        cart_key = f'cart_{shop_id}_{user_id}'
        cart = session.get(cart_key, [])

        cart = [item for item in cart if item['product_id'] != product_id]

        session[cart_key] = cart
        session.modified = True

        return {
            'success': True,
            'cart': cart,
            'cart_count': sum(i['quantity'] for i in cart),
            'cart_total': sum(i['price'] * i['quantity'] for i in cart)
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
    def search(shop_id: int, query: str, category_id: Optional[int] = None) -> List[Dict]:
        """
        Search products with comprehensive error handling and result formatting
        
        Args:
            shop_id: ID of the shop to search in
            query: Search term
            category_id: Optional category filter
            
        Returns:
            List of product dictionaries with essential fields
        """
        try:
            results = ProductRepository.search_available(
                shop_id=shop_id,
                query=query,
                category_id=category_id
            )
            
            return [{
                'id': p.id,
                'name': p.name,
                'price': float(p.selling_price),  
                'image': p.image_url or '/static/images/product-placeholder.png',
                'category': p.category.name,
                'category_id': p.category.id,
                'stock': p.stock,
                'barcode': p.barcode or ''
            } for p in results]

            
        except Exception as e:
            logger.error(f"Product search failed for shop {shop_id}: {str(e)}")
            return []

    @staticmethod
    def get_available_for_sale(shop_id: int) -> List[Dict]:
        """
        Get all available products for a shop with inventory status
        
        Args:
            shop_id: ID of the shop
            
        Returns:
            List of product dictionaries with availability info
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
                'is_low_stock': p.stock < 10
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
                        'category_id': p.category_id
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
        """Calculate tax amount based on shop location"""
        # Simplified - in reality would use shop's tax rules
        return round(subtotal * 0.1, 2)  # 10% tax

    @staticmethod
    def get_rates(shop_id: int) -> List[Dict]:
        """Get applicable tax rates for display"""
        return [{
            'name': 'VAT',
            'rate': 10.0,
            'inclusive': False
        }]



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


from flask import current_app
from sqlalchemy import func, desc, and_, or_
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .. import db
from ..models import Product, Category, Sale, CartItem, RegisterSession 
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload, with_loader_criteria
from decimal import Decimal, InvalidOperation

class ProductRepository:
    @staticmethod
    def get_available_for_sale(shop_id: int) -> List[Product]:
        """
        Get all active products available for sale in the shop
        Args:
            shop_id: ID of the shop
        Returns:
            List of available Product objects
        """
        return db.session.query(Product).join(Category).filter(
            and_(
                Category.shop_id == shop_id,
                Category.is_active == True,
                Product.is_active == True,
                Product.stock > 0
            )
        ).order_by(Product.name).all()


    @staticmethod
    def get_for_sale(product_id: int, shop_id: int) -> Optional[Product]:
        return Product.query.filter_by(
            id=product_id,
            shop_id=shop_id,
            is_active=True
        ).filter(Product.stock > 0).first()


        
    @staticmethod
    def search_available(
        shop_id: int, 
        query: str, 
        category_id: Optional[int] = None,
        in_stock_only: bool = True,
        limit: Optional[int] = None
    ) -> List[Product]:
        base_filters = [
            Category.shop_id == shop_id,
            Product.is_active == True,
            Category.is_active == True,
            or_(
                Product.name.ilike(f'%{query}%'),
                Product.barcode.ilike(f'%{query}%'),
                Product.sku.ilike(f'%{query}%')
            )
        ]

        if in_stock_only:
            base_filters.append(Product.stock > 0)

        # Apply filters and ordering first
        search_query = db.session.query(Product).join(Category).filter(
            and_(*base_filters)
        ).order_by(Product.name)

        if category_id:
            search_query = search_query.filter(Product.category_id == category_id)

        # Only apply limit after order_by
        if limit:
            search_query = search_query.limit(limit)

        return search_query.all()



    @staticmethod
    def get_featured_products(shop_id: int, limit: int = 12) -> List[Product]:
        """
        Get frequently purchased products for quick access
        Args:
            shop_id: ID of the shop
            limit: Maximum number of products to return
        Returns:
            List of featured Product objects
        """
        return db.session.query(Product)\
            .join(CartItem, Product.id == CartItem.product_id)\
            .join(Category)\
            .filter(
                and_(
                    Category.shop_id == shop_id,
                    Product.is_active == True,
                    Product.stock > 0,
                    CartItem.sale_id != None  # Only products that have been sold
                )
            )\
            .group_by(Product.id)\
            .order_by(func.count(CartItem.id).desc())\
            .limit(limit)\
            .all()
    @staticmethod
    def get_bulk_for_sale_and_session(product_ids: List[int], shop_id: int):
        products = Product.query.filter(
            Product.id.in_(product_ids),
            Product.shop_id == shop_id,
            Product.is_deleted == False
        ).all()

        register_session = RegisterSession.query.filter_by(
            shop_id=shop_id,
            closed_at=None,
            is_deleted=False
        ).first()

        return products, register_session
                
    @staticmethod
    def update_stock(product_id: int, quantity_change: int) -> bool:
        """
        Update product stock levels
        Args:
            product_id: ID of product to update
            quantity_change: Amount to adjust stock by (positive or negative)
        Returns:
            True if successful, False otherwise
        """
        try:
            product = db.session.query(Product).get(product_id)
            if not product:
                return False
                
            new_stock = product.stock + quantity_change
            if new_stock < 0:
                return False  # Prevent negative stock
                
            product.stock = new_stock
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False





class CategoryRepository:
    @staticmethod
    def get_for_pos(shop_id: int) -> List[Category]:
        """
        Get categories with their active, in-stock products for POS display
        """
        return db.session.query(Category)\
            .filter(
                and_(
                    Category.shop_id == shop_id,
                    Category.is_active == True
                )
            )\
            .options(
                joinedload(Category.products)
                    .load_only(
                        Product.id,
                        Product.name,
                        Product.selling_price,
                        Product.image_url,
                        Product.stock,
                        Product.barcode,
                        Product.category_id
                    ),
                with_loader_criteria(
                    Product,
                    lambda p: and_(p.is_active == True, p.stock > 0),
                    include_aliases=True
                )
            )\
            .order_by(Category.position, Category.name)\
            .all()

    @staticmethod
    def get_ranked_categories(shop_id: int, limit: int = None) -> List[Category]:
        """
        Get categories ordered by sales volume (best selling first)
        Args:
            shop_id: ID of the shop
            limit: Optional limit on number of categories to return
        Returns:
            List of Category objects ordered by sales volume
        """
        query = db.session.query(Category)\
            .join(Product, Category.products)\
            .join(SaleItem, Product.sale_items)\
            .filter(
                and_(
                    Category.shop_id == shop_id,
                    Category.is_active == True
                )
            )\
            .group_by(Category.id)\
            .order_by(func.count(SaleItem.id).desc())
            
        if limit:
            query = query.limit(limit)
            
        return query.all()

    @staticmethod
    def get_category_with_products(shop_id: int, category_id: int) -> Optional[Category]:
        """
        Get a single category with its active products
        Args:
            shop_id: ID of the shop
            category_id: ID of the category to retrieve
        Returns:
            Category object if found, None otherwise
        """
        return db.session.query(Category)\
            .filter(
                and_(
                    Category.id == category_id,
                    Category.shop_id == shop_id,
                    Category.is_active == True
                )
            )\
            .options(
                db.joinedload(Category.products)
                .filter(Product.is_active == True)
                .order_by(Product.name)
            )\
            .first()


class SaleRepository:
    @staticmethod
    def get_daily_summary(shop_id: int, session_id: int = None) -> Dict[str, float]:
        """
        Get sales summary with optional session filter
        """
        today = datetime.utcnow().date()
        query = db.session.query(
            func.count(Sale.id).label('count'),
            func.sum(Sale.total).label('total'),
            func.sum(Sale.subtotal).label('subtotal'),
            func.sum(Sale.tax).label('tax'),
            func.sum(CartItem.quantity * Product.cost_price).label('total_cost')
        ).join(CartItem, Sale.id == CartItem.sale_id)\
         .join(Product, CartItem.product_id == Product.id)\
         .filter(Sale.shop_id == shop_id)

        if session_id:
            query = query.filter(Sale.register_session_id == session_id)
        else:
            query = query.filter(func.date(Sale.date) == today)

        result = query.first()

        return {
            'count': result.count or 0,
            'total': float(result.total or 0),
            'subtotal': float(result.subtotal or 0),
            'tax': float(result.tax or 0),
            'total_cost': float(result.total_cost or 0),
            'total_profit': float(result.total or 0) - float(result.total_cost or 0)
        }

    @staticmethod
    def get_session_sales_total(session_id: int) -> Decimal:
        """Get total sales amount for a register session"""
        result = db.session.query(
            func.coalesce(func.sum(Sale.total), Decimal(0))
        ).filter(
            Sale.register_session_id == session_id
        ).scalar()
        return Decimal(result)

    @staticmethod
    def get_recent_sales(shop_id: int, limit: int = 5, session_id: int = None) -> List[Sale]:
        """Get recent sales with optional session filter"""
        query = db.session.query(Sale)\
            .filter(Sale.shop_id == shop_id)\
            .order_by(Sale.date.desc())

        if session_id:
            query = query.filter(Sale.register_session_id == session_id)

        return query.limit(limit).all()

    @staticmethod
    def get_sale_with_items(sale_id: int, shop_id: int) -> Optional[Sale]:
        """Get complete sale data with items"""
        return db.session.query(Sale)\
            .filter(
                and_(
                    Sale.id == sale_id,
                    Sale.shop_id == shop_id
                )
            )\
            .options(
                db.joinedload(Sale.cart_items)
                .joinedload(CartItem.product)
            )\
            .first()

    @staticmethod
    def create_sale(
        shop_id: int,
        user_id: int,
        cart_items: List[Dict],
        payment_method: str,
        customer_name: Optional[str] = None
    ) -> Sale:
        """
        Create a new sale record using CartItem as sale items
        """
        # Calculate totals
        subtotal = sum(item['price'] * item['quantity'] for item in cart_items)
        tax = subtotal * 0 
        total = subtotal + tax

        # Create sale
        sale = Sale(
            shop_id=shop_id,
            user_id=user_id,
            total=total,
            subtotal=subtotal,
            tax=tax,
            payment_method=payment_method,
            customer_name=customer_name
        )
        db.session.add(sale)
        db.session.flush()

        # Add cart items as sale items
        for item in cart_items:
            cart_item = CartItem(
                shop_id=shop_id,
                product_id=item['product_id'],
                quantity=item['quantity'],
                sale_id=sale.id
            )
            db.session.add(cart_item)

        return sale




class RegisterSessionRepository:

    @staticmethod
    def get_by_id(session_id: int) -> Optional[RegisterSession]:
        """Fetch a register session by its ID."""
        return RegisterSession.query.get(session_id)

    @staticmethod
    def get_open_session(shop_id: int) -> Optional[RegisterSession]:
        """Return the currently open session for a shop, if any."""
        session = RegisterSession.query.filter_by(
            shop_id=shop_id,
            closed_at=None,
            is_deleted=False
        ).first()

        if session:
            if session.opening_cash is None or session.opening_cash < 0:
                raise ValueError("Invalid opening cash in session.")
        return session

    @staticmethod
    def get_all(shop_id: int) -> List[RegisterSession]:
        """List all register sessions for a shop in reverse open order."""
        return RegisterSession.query.filter_by(
            shop_id=shop_id,
            is_deleted=False
        ).order_by(RegisterSession.opened_at.desc()).all()

    @staticmethod
    def create(shop_id: int, user_id: int, opening_cash: float) -> RegisterSession:
        """Create a new register session after validations."""
        try:
            opening_cash = Decimal(str(opening_cash)).quantize(Decimal('0.00'))
            if opening_cash < 0:
                raise ValueError("Opening cash must be positive.")

            if RegisterSessionRepository.get_open_session(shop_id):
                raise ValueError("Register is already open.")

            session = RegisterSession(
                shop_id=shop_id,
                opened_by_id=user_id,
                opening_cash=opening_cash
            )
            db.session.add(session)
            db.session.commit()
            return session

        except (TypeError, ValueError, InvalidOperation) as e:
            db.session.rollback()
            raise ValueError(f"Register creation failed: {str(e)}")

    @staticmethod
    def get_session_summary(session_id: int) -> Optional[Dict[str, Decimal]]:
        """Return total sales and expected cash for a session."""
        session = RegisterSession.query.get(session_id)
        if not session:
            return None

        total_sales = Decimal(str(SaleRepository.get_session_sales_total(session_id)))
        opening_cash = Decimal(str(session.opening_cash or 0))
        expected_cash = opening_cash + total_sales

        return {
            'session': session,
            'total_sales': total_sales,
            'expected_cash': expected_cash
        }

    @staticmethod
    def calculate_expected_cash(session_id: int) -> Decimal:
        """
        Compute expected cash in the register based on sales and opening cash.
        """
        session = RegisterSession.query.get_or_404(session_id)

        if session.closed_at:
            return session.expected_cash or Decimal('0.00')

        total_sales = db.session.query(
            func.coalesce(func.sum(Sale.total), 0)
        ).filter(
            Sale.register_session_id == session_id
        ).scalar()

        return Decimal(str(session.opening_cash or 0)) + Decimal(str(total_sales or 0))

    @staticmethod
    def close(session_id: int, user_id: int, closing_cash: float, expected_cash: Decimal, notes: str = None) -> RegisterSession:
        try:
            session = RegisterSession.query.get_or_404(session_id)

            if session.closed_at:
                raise ValueError("Session is already closed.")

            closing_cash = Decimal(str(closing_cash)).quantize(Decimal('0.00'))
            expected_cash = Decimal(str(expected_cash)).quantize(Decimal('0.00'))

            if closing_cash < 0:
                raise ValueError("Closing cash must be positive.")

            session.closing_cash = closing_cash
            session.closed_by_id = user_id
            session.closed_at = datetime.utcnow()
            session.expected_cash = expected_cash
            session.discrepancy = closing_cash - expected_cash
            session.notes = notes or ""

            db.session.commit()
            return session

        except (TypeError, ValueError, InvalidOperation) as e:
            db.session.rollback()
            raise ValueError(f"Failed to close register session: {str(e)}")

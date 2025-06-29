from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from enum import Enum
from datetime import datetime
from sqlalchemy import func, Index, ForeignKey
from sqlalchemy.orm import validates, relationship
from app import db
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Enum as SQLAlchemyEnum
import enum
import logging

from sqlalchemy import Numeric, Integer, Float, ForeignKey, String, DateTime, JSON




# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Define Python Enum for unit types
class UnitType(enum.Enum):
    piece = 'piece'
    weight = 'weight'

# User Roles Enum
class Role(Enum):
    ADMIN = 'admin'
    CASHIER = 'cashier'
import enum

class AdjustmentType(enum.Enum):
    addition = "addition"  # Adding stock
    reduction = "reduction"
    returned = "returned"  # Stock returned from sales
    inventory_adjustment = "inventory_adjustment"  # Adjustments made during inventory counts
    damage = "damage"  # Stock that is damaged and unsellable

    def __str__(self):
        return self.value.capitalize()  # Capitalizes the string representation


# User Model with Role-based Access
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)  
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.Enum(Role), nullable=False)

    sales = relationship('Sale', back_populates='user')
    __table_args__ = (Index('ix_user_role', 'role'),)  # Index on role for faster queries

    def set_password(self, password):
        """Hashes the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Checks if the password is correct."""
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == Role.ADMIN

    def is_cashier(self):
        return self.role == Role.CASHIER

class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(100), unique=True, nullable=False, index=True)
    products = relationship('Product', backref='category', lazy='dynamic')

    @property
    def product_count(self):
        # Returns the count of products in this category
        return self.products.count()

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'product_count': self.product_count,  # Include this if needed in API
            'products': [product.serialize() for product in self.products]
        }

    def __repr__(self):
        return f'<Category {self.name}>'


class Sale(db.Model):
    __tablename__ = 'sales'

    id = db.Column(Integer, primary_key=True)
    date = db.Column(DateTime, default=datetime.utcnow, index=True)
    total = db.Column(Float, nullable=False)
    profit = db.Column(Float, nullable=True)
    payment_method = db.Column(String(50), nullable=False)
    customer_name = db.Column(String(200), nullable=True)
    user_id = db.Column(Integer, db.ForeignKey('users.id'))  # Associate with User
    
    # Relationships
    cart_items = relationship('CartItem', back_populates='sale')
    user = relationship('User')  

    __table_args__ = (
        db.Index('ix_sale_total', 'total'),
        db.Index('ix_sale_date', 'date'),
    )

    @validates('payment_method')
    def validate_payment_method(self, key, value):
        """Ensure payment method is one of the allowed types."""
        allowed_methods = {'cash', 'mpesa', 'credit'}
        if value not in allowed_methods:
            raise ValueError(f"Invalid payment method: {value}")
        return value

    def serialize(self):
        """Serialize sale object for API response."""
        return {
            'id': self.id,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'total': self.total,
            'profit': self.profit,
            'payment_method': self.payment_method,
            'customer_name': self.customer_name,
            'user': {
                'id': self.user.id if self.user else None,
                'username': self.user.username if self.user else None,
                'role': self.user.role.value if self.user else None
            },
            'items': [item.serialize() for item in self.cart_items],
        }

    @classmethod
    def create_sale(cls, total, profit, payment_method, customer_name, user_id=None):
        """Create a new sale instance."""
        return cls(
            date=datetime.utcnow(),
            total=total,
            profit=profit,
            payment_method=payment_method,
            customer_name=customer_name,
            user_id=user_id
        )

    def finalize_sale(self):
        """Finalize the sale by updating stock and committing to the database."""
        try:
            # Check stock availability for each cart item
            for item in self.cart_items:
                if item.product.stock < item.quantity:
                    raise ValueError(f"Not enough stock for {item.product.name}")

            # Update stock and finalize the sale
            for item in self.cart_items:
                item.product.stock -= item.quantity

            db.session.commit()  # Commit changes if everything is valid
        except Exception as e:
            db.session.rollback()  # Rollback in case of error
            raise ValueError(f"Error finalizing sale: {str(e)}")

    def __repr__(self):
        return f'<Sale id={self.id}, total={self.total}, date={self.date.strftime("%Y-%m-%d %H:%M:%S")}>'




class CartItem(db.Model):
    __tablename__ = 'cart_items'
    
    id = db.Column(Integer, primary_key=True)
    product_id = db.Column(Integer, ForeignKey('products.id'), nullable=False)
    quantity = db.Column(Integer, nullable=False)
    sale_id = db.Column(Integer, ForeignKey('sales.id'), nullable=False)

    product = relationship('Product', back_populates='sale_items', lazy='select')  # Changed to select for efficiency
    sale = relationship('Sale', back_populates='cart_items')

    __table_args__ = (
        db.Index('ix_product_sale', 'product_id', 'sale_id'),  # Composite index for faster lookups
    )

    @validates('quantity')
    def validate_quantity(self, key, value):
        """Ensure the quantity is greater than zero."""
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    @hybrid_property
    def total_price(self):
        """Calculate total price dynamically."""
        return self.quantity * (self.product.selling_price if self.product else 0.0)

    def __repr__(self):
        return f'<CartItem product_id={self.product_id}, quantity={self.quantity}>'

    def serialize(self):
        """Serialize the cart item for API response."""
        return {
            'product_name': self.product.name if self.product else 'Unknown Product',
            'quantity': self.quantity,
            'total_price': str(self.total_price),  # Convert to string for JSON serialization
        }

class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(200), nullable=False)

    cost_price = db.Column(Numeric(10, 2), nullable=False, default=0.00)
    selling_price = db.Column(Numeric(10, 2), nullable=False, default=0.00)
    stock = db.Column(Integer, nullable=False, default=0)

    category_id = db.Column(Integer, db.ForeignKey('categories.id'), nullable=False, index=True)
    supplier_id = db.Column(Integer, db.ForeignKey('suppliers.id'), nullable=True, index=True)

    combination_size = db.Column(Integer, nullable=True)
    combination_price = db.Column(Numeric(10, 2), nullable=True)
    combination_unit_price = db.Column(Numeric(10, 2), nullable=True)
    created_at = db.Column(DateTime, default=datetime.utcnow)

    # Relationship
    sale_items = db.relationship('CartItem', back_populates='product', lazy='select')

    @validates('cost_price', 'selling_price', 'stock')
    def validate_prices_stock(self, key, value):
        if key in ['cost_price', 'selling_price'] and value < 0:
            raise ValueError(f"{key.replace('_', ' ').title()} cannot be negative.")
        if key == 'stock' and value < 0:
            raise ValueError("Stock cannot be negative.")
        return value

    @hybrid_property
    def profit(self):
        return self.selling_price - self.cost_price

    @hybrid_property
    def profit_margin(self):
        return (self.profit / self.selling_price * 100) if self.selling_price > 0 else 0.0

    def is_low_stock(self):
        return self.stock < 10

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'cost_price': str(self.cost_price),
            'selling_price': str(self.selling_price),
            'stock': self.stock,
            'combination_size': self.combination_size,
            'combination_price': str(self.combination_price) if self.combination_price else None,
            'profit': str(self.profit),
            'profit_margin': float(round(self.profit_margin, 2)),
            'supplier_id': self.supplier_id
        }

    def __repr__(self):
        return f'<Product(name={self.name}, supplier_id={self.supplier_id}, stock={self.stock})>'




class Supplier(db.Model):
    __tablename__ = 'suppliers'
    
    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(200), nullable=False)  # Removed unique=True
    phone = db.Column(String(20), nullable=True)
    
    products = relationship('Product', backref='supplier', lazy='select')  # Changed to select for efficiency

    def __repr__(self):
        return f'<Supplier {self.name}>'

    def serialize(self):
        """Serialize the supplier object."""
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'product_count': len(self.products),  # Include count of products for context
            'products': [product.serialize() for product in self.products]  # Serialize all products
        }

class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(Integer, primary_key=True)
    description = db.Column(String(200), nullable=False)
    amount = db.Column(Numeric(10, 2), nullable=False)  # Changed to Numeric for precision
    date = db.Column(DateTime, default=datetime.utcnow, index=True)
    category = db.Column(String(100), nullable=True, default="Daily Expenses")  # Default category
    product_id = db.Column(Integer, ForeignKey('products.id'), nullable=True)
    quantity = db.Column(Integer, nullable=True)

    __table_args__ = (
        Index('ix_expense_date_category', 'date', 'category'),  # Composite index
    )

    product = relationship('Product', backref='expenses', lazy='select')  # Changed to select for efficiency

    @validates('amount', 'quantity')
    def validate_amount_quantity(self, key, value):
        """Validate that the expense amount and quantity are positive."""
        if key == 'amount' and value <= 0:  # Allow zero only for quantity
            raise ValueError("Expense amount must be positive.")
        if key == 'quantity' and value <= 0:
            raise ValueError("Quantity must be positive.")
        return value

    def serialize(self):
        """Serialize the expense object."""
        return {
            'id': self.id,
            'description': self.description,
            'amount': str(self.amount),  # Convert to string for JSON serialization
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'category': self.category,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'product_name': self.product.name if self.product else None  # Optional product name
        }



class StockLog(db.Model):
    __tablename__ = 'stock_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.DateTime, default=func.now())
    previous_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    adjustment_type = db.Column(SQLAlchemyEnum(AdjustmentType), nullable=False)  
    change_reason = db.Column(db.String(200), nullable=True)
    log_metadata = db.Column(JSON, nullable=True) 
    
    product = db.relationship('Product', back_populates='stock_logs')
    user = db.relationship('User', back_populates='stock_logs')
    
    def __repr__(self):
        return f"<StockLog(product_id={self.product_id}, previous_stock={self.previous_stock}, new_stock={self.new_stock})>"

# Adding stock_logs relationship to Product and User models
Product.stock_logs = db.relationship('StockLog', order_by=StockLog.date, back_populates='product')
User.stock_logs = db.relationship('StockLog', back_populates='user')        





class PriceChange(db.Model):
    __tablename__ = 'price_changes'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    change_type = db.Column(db.String(50), nullable=False)  
    old_price = db.Column(db.Numeric(10, 2), nullable=False)
    new_price = db.Column(db.Numeric(10, 2), nullable=False)
    old_combo_size = db.Column(db.Integer, nullable=True)
    old_combo_price = db.Column(db.Numeric(10, 2), nullable=True)
    new_combo_size = db.Column(db.Integer, nullable=True)
    new_combo_price = db.Column(db.Numeric(10, 2), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship('Product', backref='price_changes')
    user = db.relationship('User', backref='price_changes')



    @classmethod
    def create_record(cls, product_id, user_id, change_type, old_price, new_price,
                     old_combo=None, new_combo=None):
        """Create and return a new price change record"""
        record = cls(
            product_id=product_id,
            user_id=user_id,
            change_type=change_type,
            old_price=old_price,
            new_price=new_price,
            old_combo_size=old_combo[0] if old_combo else None,
            old_combo_price=old_combo[1] if old_combo else None,
            new_combo_size=new_combo[0] if new_combo else None,
            new_combo_price=new_combo[1] if new_combo else None
        )
        db.session.add(record)
        return record
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from enum import Enum
from datetime import datetime
from sqlalchemy import func, Index, ForeignKey
from sqlalchemy.orm import validates
from app import db
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Enum as SQLAlchemyEnum
import enum
import logging

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

# User Model with Role-based Access
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)  
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.Enum(Role), nullable=False)

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

# Category Model
class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    products = db.relationship('Product', backref='category', lazy='joined')

# Sale Model with Auto Stock Update and Total Price Indexing
class Sale(db.Model):
    __tablename__ = 'sales'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    total = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)  # 'cash', 'mpesa', 'credit'
    customer_name = db.Column(db.String(200), nullable=True)
    cart_items = db.relationship('CartItem', backref='sale', lazy='joined')

    __table_args__ = (Index('ix_sale_total', 'total'), Index('ix_sale_date', 'date'))

    @validates('payment_method')
    def validate_payment_method(self, key, value):
        allowed_methods = {'cash', 'mpesa', 'credit'}
        if value not in allowed_methods:
            raise ValueError(f"Invalid payment method: {value}")
        return value

    def serialize(self):
        """Convert the Sale object to a dictionary format for JSON serialization."""
        return {
            'id': self.id,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'total': self.total,
            'payment_method': self.payment_method,
            'customer_name': self.customer_name,
            'items': [item.serialize() for item in self.cart_items]
        }

    def finalize_sale(self):
        """Automatically updates stock after a sale."""
        try:
            for item in self.cart_items:
                if item.product.stock < item.quantity:
                    raise ValueError(f"Not enough stock for {item.product.name}")
            
            for item in self.cart_items:
                item.product.stock -= item.quantity

            db.session.commit()
        except Exception as e:
            db.session.rollback()  # Rollback the session in case of error
            raise ValueError(f"Error finalizing sale: {str(e)}")

# CartItem Model
class CartItem(db.Model):
    __tablename__ = 'cart_items'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)

    @validates('quantity')
    def validate_quantity(self, key, value):
        """Validate that the quantity is greater than zero."""
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    def __repr__(self):
        return f'<CartItem product_id={self.product_id}, quantity={self.quantity}>'

    def serialize(self):
        """Convert the CartItem object to a dictionary format for JSON serialization."""
        product = self.product
        return {
            'product_name': product.name,
            'quantity': self.quantity,
            'total_price': self.quantity * product.selling_price,  # Calculate total based on selling price
            'profit_per_item': product.calculate_profit()[0]  # Profit per item
        }
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0.0)
    selling_price = db.Column(db.Float, nullable=False, default=0.0)
    stock = db.Column(db.Float, nullable=False, default=0.0)  # Holds count for pieces, weight for weight-based
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    unit_type = db.Column(SQLAlchemyEnum(UnitType, name='unit_types'), nullable=False)
    packet_size = db.Column(db.Integer, nullable=True)  # For piece products only
    combination_size = db.Column(db.Integer, nullable=True)  # For combination sales
    combination_price = db.Column(db.Float, nullable=True)  # For combination sales
    combination_unit_price = db.Column(db.Float, nullable=True)
    bulk_quantity = db.Column(db.Float, nullable=True)  # Total bulk weight for weight products
    sale_items = db.relationship('CartItem', backref='product', lazy='joined')

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
        logging.debug(f"Checking stock for product: {self.name}, Unit Type: {self.unit_type}, Stock: {self.stock}")
        return self.stock < (10 if self.unit_type == UnitType.piece else 1.0)

    def is_weight_based(self):
        """Determine if the product is weight-based."""
        return self.unit_type == UnitType.weight

    def is_piece_based(self):
        """Determine if the product is piece-based."""
        return self.unit_type == UnitType.piece

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'cost_price': self.cost_price,
            'selling_price': self.selling_price,
            'stock': self.stock,
            'unit_type': self.unit_type.name,
            'packet_size': self.packet_size,
            'combination_size': self.combination_size,
            'combination_price': self.combination_price,
            'profit': self.profit,
            'profit_margin': self.profit_margin,
            'supplier_id': self.supplier_id
        }

    def __repr__(self):
        return f'<Product {self.name}, Supplier ID {self.supplier_id}>'


class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=True)    
    products = db.relationship('Product', backref='supplier', lazy='joined') 

    def __repr__(self):
        return f'<Supplier {self.name}>'

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'products': [product.serialize() for product in self.products]  # Serialize all products
        }

class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False) 
    date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    category = db.Column(db.String(100), nullable=True, default="Daily Expenses")  # Default category
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  
    quantity = db.Column(db.Integer, nullable=True)  
   
    __table_args__ = (Index('ix_expense_date', 'date'),)

    @validates('amount', 'quantity')
    def validate_amount_quantity(self, key, value):
        """Validate that the expense amount and quantity are positive."""
        if key == 'amount' and value < 0:
            raise ValueError("Expense amount cannot be negative.")
        if key == 'quantity' and value < 0:
            raise ValueError("Quantity cannot be negative.")
        return value

    def serialize(self):
        return {
            'id': self.id,
            'description': self.description,
            'amount': self.amount,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'category': self.category,
            'product_id': self.product_id,
            'quantity': self.quantity
        }

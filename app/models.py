from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from enum import Enum
from datetime import datetime
from sqlalchemy import func, Index, ForeignKey
from sqlalchemy.orm import validates
from app import db

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

# Product Model with Cost Price, Selling Price, and Profit Calculation
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cost_price = db.Column(db.Float, nullable=False, default=0.0)
    selling_price = db.Column(db.Float, nullable=False, default=0.0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    sale_items = db.relationship('CartItem', backref='product', lazy='joined')

    @validates('cost_price', 'selling_price', 'stock')
    def validate_cost_selling_stock(self, key, value):
        if key in ['cost_price', 'selling_price'] and value < 0:
            raise ValueError(f"{key.replace('_', ' ').title()} cannot be negative")
        if key == 'stock' and value < 0:
            raise ValueError("Stock cannot be negative")
        return value

    def calculate_profit(self):
        """Calculates profit per item sold."""
        return self.selling_price - self.cost_price if self.selling_price > self.cost_price else 0.0

    def is_low_stock(self):
        return self.stock < 10

    def __repr__(self):
        return f'<Product {self.name}, Supplier {self.supplier_id}>'


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
        for item in self.cart_items:
            if item.product.stock < item.quantity:
                raise ValueError(f"Not enough stock for {item.product.name}")
        for item in self.cart_items:
            item.product.stock -= item.quantity
        db.session.commit()

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
            'profit_per_item': product.calculate_profit()  # Profit per item
        }

class Expense(db.Model):
    __tablename__ = 'expenses'
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)  # Total expense amount
    date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    category = db.Column(db.String(100), nullable=False)  # e.g., 'utilities', 'rent', etc.
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # Optional product link
    quantity = db.Column(db.Integer, nullable=False)  # Quantity purchased
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)  # Supplier reference

    __table_args__ = (Index('ix_expense_date', 'date'),)

    @validates('amount', 'quantity')
    def validate_amount(self, key, value):
        """Validate that the expense amount and quantity are not negative."""
        if key == 'amount' and value < 0:
            raise ValueError("Expense amount cannot be negative")
        if key == 'quantity' and value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    def calculate_total_cost(self):
        """Calculate the total cost based on cost price and quantity."""
        product = Product.query.get(self.product_id)
        if product:
            return product.cost_price * self.quantity
        return 0.0

    def finalize_expense(self):
        """Update product stock based on the expense."""
        if self.product_id:
            product = Product.query.get(self.product_id)
            if product:
                product.stock += self.quantity  # Increment stock by the purchased quantity
        db.session.commit()

    def serialize(self):
        """Convert the Expense object to a dictionary format for JSON serialization."""
        return {
            'id': self.id,
            'description': self.description,
            'amount': self.amount,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'category': self.category,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'supplier_id': self.supplier_id
        }



class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    contact_person = db.Column(db.String(100), nullable=True)  # Optional contact person
    phone = db.Column(db.String(20), nullable=True)  # Optional phone number
    email = db.Column(db.String(100), nullable=True)  # Optional email address
    address = db.Column(db.String(250), nullable=True)  # Optional address
    products = db.relationship('Product', backref='supplier', lazy='joined')  # Relationship with Product

    def __repr__(self):
        return f'<Supplier {self.name}>'
  
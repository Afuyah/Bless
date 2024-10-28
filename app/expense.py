from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from app import db, admin_required
from app.models import Expense
import logging
from datetime import datetime

expense_bp = Blueprint('expense', __name__)


@expense_bp.route('/expenses')
@login_required
def expenses_page():
    return render_template('expenses.html')  # Create this template


@expense_bp.route('/api/expenses', methods=['GET'])
@login_required
def get_expenses():
    date_filter = request.args.get('date')
    query = Expense.query

    if date_filter:
        # Assuming date_filter is in the format YYYY-MM-DD
        query = query.filter(Expense.date >= f"{date_filter} 00:00:00", 
                             Expense.date <= f"{date_filter} 23:59:59")
    
    expenses = query.all()
    return jsonify([{
        'id': expense.id,
        'description': expense.description,
        'amount': expense.amount,
        'date': expense.date.strftime("%Y-%m-%d %H:%M:%S"),
        'category': expense.category
    } for expense in expenses])




@expense_bp.route('/api/add_daily_expense', methods=['POST'])
@login_required
def add_daily_expense():
    try:
        # Parse JSON data
        data = request.get_json()
        logging.info(f"Received data: {data}")  

        description = data.get('description')
        amount = data.get('amount')

        # Validate data
        if not description or not amount or float(amount) <= 0:
            logging.error("Invalid input data")
            return jsonify({'error': 'Invalid input data'}), 400

        # Create and log new daily expense with category set to "Daily Expenses"
        new_expense = Expense(
            description=description,
            amount=float(amount),
            category="Daily Expenses",
            date=datetime.now(),
        )
        db.session.add(new_expense)
        db.session.commit()
        logging.info("Daily expense added successfully.")

        return jsonify({'message': 'Daily expense added successfully.'}), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error adding daily expense: {e}")
        return jsonify({'error': 'Failed to add daily expense. Please try again.'}), 500

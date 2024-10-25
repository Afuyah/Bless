from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required, current_user
from app import db
from app.models import Expense

expense_bp = Blueprint('expense', __name__)


@expense_bp.route('/expenses')
def expenses_page():
    return render_template('expenses.html')  # Create this template


@expense_bp.route('/api/expenses', methods=['GET'])
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

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.models import Product, Issuance
from app.class_options import CLASS_OPTIONS

teacher_bp = Blueprint('teacher_bp', __name__, url_prefix='/teacher')


def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'teacher':
            flash('Access denied — Teacher only')
            return redirect(url_for('auth.dashboard'))
        return f(*args, **kwargs)
    return decorated


@teacher_bp.route('/issue', methods=['GET', 'POST'])
@login_required
@teacher_required
def issue_item():
    city_id = current_user.city_id

    if request.method == 'POST':
        product_id = request.form.get('product_id')
        quantity = request.form.get('quantity', '').strip()
        student_name = request.form.get('student_name', '').strip()
        student_class = request.form.get('student_class', '').strip() or None
        notes = request.form.get('notes', '').strip() or None

        if not product_id or not quantity or not student_name:
            flash('Product, quantity and student name are required')
            return redirect(url_for('teacher_bp.issue_item'))

        try:
            quantity = int(quantity)
        except ValueError:
            flash('Quantity must be a number')
            return redirect(url_for('teacher_bp.issue_item'))

        product = Product.query.get(int(product_id))
        if not product or product.city_id != city_id or not product.is_active:
            flash('Invalid product selected')
            return redirect(url_for('teacher_bp.issue_item'))

        if product.stock_quantity < quantity:
            flash(f'Not enough stock for "{product.name}" (available: {product.stock_quantity})')
            return redirect(url_for('teacher_bp.issue_item'))

        issuance = Issuance(
            teacher_id=current_user.id,
            city_id=city_id,
            product_id=product.id,
            product_name=product.name,
            quantity=quantity,
            student_name=student_name,
            student_class=student_class,
            notes=notes
        )
        product.stock_quantity -= quantity
        db.session.add(issuance)
        db.session.commit()

        flash(f'Issued {quantity} x "{product.name}" to {student_name}')
        return redirect(url_for('teacher_bp.issue_item'))

    products = Product.query.filter_by(city_id=city_id, is_active=True).order_by(Product.name).all()
    return render_template('teacher/issue.html', products=products, class_options=CLASS_OPTIONS)


@teacher_bp.route('/history')
@login_required
@teacher_required
def my_history():
    records = Issuance.query.filter_by(teacher_id=current_user.id).order_by(Issuance.issued_at.desc()).all()
    return render_template('teacher/history.html', records=records)
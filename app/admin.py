from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.inventory import class_value_to_key, get_active_city_id
from app.models import City, User
from app.activity_log import log_activity
from app.inventory import store_staff_required

admin = Blueprint('admin', __name__, url_prefix='/admin')


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'super_admin':
            flash('Access denied — Super Admin only')
            return redirect(url_for('auth.dashboard'))
        return f(*args, **kwargs)
    return decorated


@admin.route('/cities', methods=['GET', 'POST'])
@login_required
@super_admin_required
def cities():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('School name cannot be empty')
        elif City.query.filter_by(name=name).first():
            flash(f'School "{name}" already exists')
        else:
            new_city = City(name=name)
            db.session.add(new_city)
            db.session.commit()
            flash(f'School "{name}" added successfully')
        return redirect(url_for('admin.cities'))

    all_cities = City.query.order_by(City.name).all()
    return render_template('admin/cities.html', cities=all_cities)


@admin.route('/cities/<int:city_id>/edit', methods=['POST'])
@login_required
@super_admin_required
def edit_city(city_id):
    city = City.query.get_or_404(city_id)
    city.extra_counter_line = request.form.get('extra_counter_line', '').strip() or None
    city.gstin_number = request.form.get('gstin_number', '').strip() or None
    city.gstin_number = request.form.get('gstin_number', '').strip() or None
    city.state = request.form.get('state', '').strip() or None
    city.invoice_prefix = request.form.get('invoice_prefix', '').strip() or None
    city.jodo_component_code = request.form.get('jodo_component_code', '').strip() or None
    city.jodo_branch_code = request.form.get('jodo_branch_code', '').strip() or None
    city.contact_email = request.form.get('contact_email', '').strip() or None
    city.contact_phone = request.form.get('contact_phone', '').strip() or None
    city.contact_email = request.form.get('contact_email', '').strip() or None
    city.contact_phone = request.form.get('contact_phone', '').strip() or None

    next_num = request.form.get('next_invoice_number', '').strip()
    if next_num.isdigit():
        city.next_invoice_number = int(next_num)
    elif not next_num:
        city.next_invoice_number = None

    db.session.commit()
    flash(f'Updated details for "{city.name}"')
    return redirect(url_for('admin.cities'))


@admin.route('/cities/<int:city_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_city(city_id):
    from app.models import (Product, Bill, User, Order, StudentRecord, TeacherRecord,
                             Bundle, ReturnRecord, PurchaseInvoiceUpload, CouponOrder, PendingJodoOrder)

    city = City.query.get_or_404(city_id)

    checks = {
        'staff': User.query.filter_by(city_id=city_id).first() is not None,
        'products': Product.query.filter_by(city_id=city_id).first() is not None,
        'bills': Bill.query.filter_by(city_id=city_id).first() is not None,
        'orders': Order.query.filter_by(city_id=city_id).first() is not None,
        'students': StudentRecord.query.filter_by(city_id=city_id).first() is not None,
        'teachers': TeacherRecord.query.filter_by(city_id=city_id).first() is not None,
        'bundles': Bundle.query.filter_by(city_id=city_id).first() is not None,
        'returns': ReturnRecord.query.filter_by(city_id=city_id).first() is not None,
        'purchase invoices': PurchaseInvoiceUpload.query.filter_by(city_id=city_id).first() is not None,
        'coupon orders': CouponOrder.query.filter_by(city_id=city_id).first() is not None,
        'pending online payments': PendingJodoOrder.query.filter_by(city_id=city_id).first() is not None,
    }

    blocking = [name for name, exists in checks.items() if exists]

    if blocking:
        flash(f'Cannot remove "{city.name}" — it still has {", ".join(blocking)} tied to it. Remove those first if this school truly needs to be deleted.')
        return redirect(url_for('admin.cities'))

    city_name = city.name
    db.session.delete(city)
    db.session.commit()
    flash(f'School "{city_name}" removed')
    return redirect(url_for('admin.cities'))


@admin.route('/staff', methods=['GET', 'POST'])
@login_required
@super_admin_required
def staff():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role')
        city_id = request.form.get('city_id')
        extra_city_ids = request.form.getlist('extra_city_ids')

        if not username or not password or not role:
            flash('Username, password and role are required')
            return redirect(url_for('admin.staff'))

        if role != 'super_admin' and not city_id:
            flash('Primary city is required for this role')
            return redirect(url_for('admin.staff'))

        if User.query.filter_by(username=username).first():
            flash(f'Username "{username}" already exists')
            return redirect(url_for('admin.staff'))

        new_user = User(
            username=username,
            role=role,
            city_id=int(city_id) if city_id else None
        )
        new_user.set_password(password)

        if role == 'store_staff' and extra_city_ids:
            extra_ids = [int(i) for i in extra_city_ids if not city_id or int(i) != int(city_id)]
            new_user.accessible_cities = City.query.filter(City.id.in_(extra_ids)).all()

        db.session.add(new_user)
        db.session.commit()
        log_activity('Created staff account', f'"{username}" ({role})')
        flash(f'User "{username}" ({role}) created successfully')
        return redirect(url_for('admin.staff'))

    all_staff = User.query.order_by(User.role, User.username).all()
    active_cities = City.query.filter_by(is_active=True).order_by(City.name).all()
    return render_template('admin/staff.html', staff=all_staff, cities=active_cities)

@admin.route('/issuances')
@login_required
@super_admin_required
def issuance_log():
    from app.models import Issuance
    records = Issuance.query.order_by(Issuance.issued_at.desc()).all()
    return render_template('admin/issuances.html', records=records)

@admin.route('/purchase-history')
@login_required
@super_admin_required
def purchase_history():
    from app.models import PurchaseRecord, City

    city_id_param = request.args.get('city_id', 'all')
    city_id = None if city_id_param == 'all' else int(city_id_param)

    query = PurchaseRecord.query
    if city_id is not None:
        query = query.filter_by(city_id=city_id)

    records = query.order_by(PurchaseRecord.created_at.desc()).all()
    all_cities = City.query.order_by(City.name).all()

    return render_template('admin/purchase_history.html', records=records, all_cities=all_cities, selected_city_id=city_id_param)


@admin.route('/purchase-history/<int:record_id>')
@login_required
@super_admin_required
def purchase_record_detail(record_id):
    from app.models import PurchaseRecord
    record = PurchaseRecord.query.get_or_404(record_id)
    return render_template('admin/purchase_record_detail.html', record=record)

@admin.route('/staff/<int:user_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_staff(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('You cannot remove your own account while logged in as it')
        return redirect(url_for('admin.staff'))

    if user.role == 'super_admin':
        flash('Cannot remove a Super Admin account from here')
        return redirect(url_for('admin.staff'))

    username = user.username
    db.session.delete(user)
    db.session.commit()
    log_activity('Removed staff account', f'"{username}"')
    flash(f'User "{username}" removed')
    return redirect(url_for('admin.staff'))

@admin.route('/activity-log')
@login_required
def activity_log():
    from app.models import ActivityLog, City
    from datetime import datetime, timedelta

    city_id_param = request.args.get('city_id', 'all')
    city_id = None if city_id_param == 'all' else int(city_id_param)

    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    query = ActivityLog.query
    if city_id is not None:
        query = query.filter_by(city_id=city_id)
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        query = query.filter(ActivityLog.created_at >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(ActivityLog.created_at < end_date)

    logs = query.order_by(ActivityLog.created_at.desc()).limit(500).all()

    all_cities = City.query.order_by(City.name).all()
    return render_template('admin/activity_log.html', logs=logs, all_cities=all_cities,
                            selected_city_id=city_id_param, start_date=start_date_str, end_date=end_date_str)

@admin.route('/parent-links')
@login_required
@super_admin_required
def parent_links():
    all_cities = City.query.filter_by(is_active=True).order_by(City.name).all()
    return render_template('admin/parent_links.html', cities=all_cities)

@admin.route('/staff/<int:user_id>/reset-password', methods=['POST'])
@login_required
@super_admin_required
def reset_staff_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()

    if not new_password or len(new_password) < 4:
        flash('Password must be at least 4 characters')
        return redirect(url_for('admin.staff'))

    user.set_password(new_password)
    db.session.commit()

    log_activity('Reset staff password', f'For user "{user.username}"')
    flash(f'Password for "{user.username}" has been reset. Tell them their new password: {new_password}')
    return redirect(url_for('admin.staff'))

@admin.route('/stock-correction', methods=['GET', 'POST'])
@login_required
@super_admin_required
def stock_correction():
    from app.models import Product, StockLog, City

    all_cities = City.query.order_by(City.name).all()
    city_id_param = request.args.get('city_id') or request.form.get('city_id')
    city_id = int(city_id_param) if city_id_param else (all_cities[0].id if all_cities else None)

    if request.method == 'POST':
        product_id = request.form.get('product_id')
        new_quantity = request.form.get('new_quantity', '').strip()
        reason = request.form.get('reason', '').strip()

        if not product_id or not new_quantity or not reason:
            flash('Product, new quantity, and a reason are all required')
            return redirect(url_for('admin.stock_correction', city_id=city_id))

        try:
            new_quantity = int(new_quantity)
        except ValueError:
            flash('Quantity must be a number')
            return redirect(url_for('admin.stock_correction', city_id=city_id))

        product = Product.query.get(int(product_id))
        if not product or product.city_id != city_id:
            flash('Invalid product')
            return redirect(url_for('admin.stock_correction', city_id=city_id))

        old_quantity = product.stock_quantity
        diff = new_quantity - old_quantity
        product.stock_quantity = new_quantity

        if diff != 0:
            db.session.add(StockLog(
                product_id=product.id, city_id=city_id,
                quantity_added=diff, created_by_id=current_user.id
            ))

        db.session.commit()

        log_activity('Stock correction', f'"{product.name}": {old_quantity} → {new_quantity} ({"+" if diff >= 0 else ""}{diff}). Reason: {reason}')
        flash(f'Stock corrected for "{product.name}": {old_quantity} → {new_quantity}')
        return redirect(url_for('admin.stock_correction', city_id=city_id))

    from app.inventory import section_label, class_value_to_key

    raw_products = Product.query.filter_by(city_id=city_id, is_active=True).order_by(Product.name).all() if city_id else []

    def sort_key(k):
        return (0, int(k)) if k.isdigit() else (1, k)

    tagged_products = []
    for p in raw_products:
        key = class_value_to_key(p.applicable_class)
        if key in ('notebook', 'extra'):
            key = 'stationary'
        p.display_label = section_label(key)
        tagged_products.append((sort_key(key), p.name, p))

    tagged_products.sort(key=lambda t: (t[0], t[1]))
    products = [t[2] for t in tagged_products]

    return render_template('admin/stock_correction.html', products=products, all_cities=all_cities,
                            selected_city_id=str(city_id) if city_id else 'all')

@admin.route('/purchase-options', methods=['GET', 'POST'])
@login_required
@super_admin_required
def purchase_options():
    all_cities = City.query.order_by(City.name).all()

    if request.method == 'POST':
        city_id = request.form.get('city_id')
        city = City.query.get_or_404(int(city_id))
        city.bundle_enabled = request.form.get('bundle_enabled') == 'on'
        city.individual_items_enabled = request.form.get('individual_items_enabled') == 'on'
        city.free_shopping_enabled = request.form.get('free_shopping_enabled') == 'on'
        db.session.commit()
        log_activity('Updated purchase options', f'"{city.name}": Bundle={city.bundle_enabled}, Individual={city.individual_items_enabled}, Free Shop={city.free_shopping_enabled}')
        flash(f'Updated purchase options for "{city.name}"')
        return redirect(url_for('admin.purchase_options'))

    return render_template('admin/purchase_options.html', all_cities=all_cities)

@admin.route('/staff-parent-link')
@login_required
@store_staff_required
def staff_parent_link():
    city_id = get_active_city_id()
    city = City.query.get_or_404(city_id)
    return render_template('admin/staff_parent_link.html', city=city)


@admin.route('/staff-purchase-options', methods=['GET', 'POST'])
@login_required
@store_staff_required
def staff_purchase_options():
    city_id = get_active_city_id()
    city = City.query.get_or_404(city_id)

    if request.method == 'POST':
        city.bundle_enabled = request.form.get('bundle_enabled') == 'on'
        city.individual_items_enabled = request.form.get('individual_items_enabled') == 'on'
        city.free_shopping_enabled = request.form.get('free_shopping_enabled') == 'on'
        db.session.commit()
        log_activity('Updated purchase options (via store staff)', f'"{city.name}": Bundle={city.bundle_enabled}, Individual={city.individual_items_enabled}, Free Shop={city.free_shopping_enabled}')
        flash('Purchase options updated')
        return redirect(url_for('admin.staff_purchase_options'))

    return render_template('admin/staff_purchase_options.html', city=city)
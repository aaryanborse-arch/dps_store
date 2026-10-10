import random
import string
from datetime import datetime, date
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from app import db
from app.models import Product, Bill, BillItem, Order, Issuance
from app.inventory import store_staff_required
from app.city_utils import get_active_city_id, get_active_city
from app.pdf_utils import generate_bill_pdf, generate_bill_pdf_three_copies
from app.excel_utils import generate_bill_excel
from app.pdf_utils import to_roman
from app.class_options import CLASS_OPTIONS, normalize_class_value, needs_stream, STREAM_OPTIONS
from app.models import CouponOrder
from app.models import Bundle
from app.models import Bundle, StudentRecord
from app.parent import normalize_admission_text
from app.bundle_rules import get_custom_shop_items, group_by_section
from app.activity_log import log_activity
from sqlalchemy import text

sales = Blueprint('sales', __name__, url_prefix='/sales')


def generate_bill_number(city):
    if city and city.invoice_prefix and city.next_invoice_number:
        result = db.session.execute(
            text('UPDATE cities SET next_invoice_number = next_invoice_number + 1 WHERE id = :city_id RETURNING next_invoice_number - 1'),
            {'city_id': city.id}
        )
        number = result.scalar()
        db.session.commit()
        return f'{city.invoice_prefix}{number}'
    date_part = datetime.utcnow().strftime('%Y%m%d')
    rand_part = ''.join(random.choices(string.digits, k=4))
    return f'BILL-{date_part}-{rand_part}'


@sales.route('/counter', methods=['GET', 'POST'])
@login_required
@store_staff_required
def counter_sale():
    city_id = get_active_city_id()

    if request.method == 'POST':
        student_name = request.form.get('student_name', '').strip()
        student_class = request.form.get('student_class', '').strip() or None
        admission_number = request.form.get('admission_number', '').strip()
        payment_method = request.form.get('payment_method', '').strip()

        if not student_name or not admission_number or not payment_method:
            flash('Student name, admission number and payment method are all required')
            return redirect(url_for('sales.counter_sale'))

        product_ids = request.form.getlist('product_id')
        quantities = request.form.getlist('quantity')

        items_to_bill = []
        for pid, qty in zip(product_ids, quantities):
            qty = int(qty) if qty and qty.isdigit() else 0
            if qty > 0:
                items_to_bill.append((int(pid), qty))

        if not items_to_bill:
            flash('Select at least one product with quantity greater than 0')
            return redirect(url_for('sales.counter_sale'))

        products_map = {}
        for pid, qty in items_to_bill:
            product = Product.query.get(pid)
            if not product or product.city_id != city_id or not product.is_active:
                flash('Invalid product selected')
                return redirect(url_for('sales.counter_sale'))
            if product.stock_quantity < qty:
                flash(f'Not enough stock for "{product.name}" (available: {product.stock_quantity})')
                return redirect(url_for('sales.counter_sale'))
            products_map[pid] = product

        from app.models import City
        active_city = City.query.get(city_id)

        new_bill = Bill(
            bill_number=generate_bill_number(active_city),
            sale_type='offline',
            city_id=city_id,
            created_by_id=current_user.id,
            buyer_name=student_name,
            buyer_phone='-',
            student_name=student_name,
            student_class=student_class,
            admission_number=admission_number,
            payment_method=payment_method,
            total_amount=0.0
        )
        db.session.add(new_bill)
        db.session.flush()

        total = 0.0
        for pid, qty in items_to_bill:
            product = products_map[pid]
            subtotal = product.price * qty
            gst_amount = 0.0 if product.is_gst_exempt else round(subtotal * product.gst_percent / 100, 2)
            line_total = subtotal + gst_amount

            item = BillItem(
                bill_id=new_bill.id,
                product_id=product.id,
                product_name=product.name,
                publisher_name=product.publisher_name,
                subject=product.subject,
                hsn_number=product.hsn_number,
                gst_percent=product.gst_percent,
                is_gst_exempt=product.is_gst_exempt,
                price=product.price,
                quantity=qty,
                subtotal=subtotal
            )
            db.session.add(item)

            product.stock_quantity -= qty
            total += line_total

        new_bill.total_amount = total
        db.session.commit()

        flash(f'Bill {new_bill.bill_number} generated successfully')
        return redirect(url_for('sales.view_bill', bill_id=new_bill.id))

    all_products = Product.query.filter_by(city_id=city_id, is_active=True).order_by(Product.name).all()

    sections = {}
    for p in all_products:
        key = p.applicable_class if p.applicable_class else 'Common Items'
        sections.setdefault(key, []).append(p)

    def sort_key(k):
        return (0, int(k)) if k.isdigit() else (1, k)

    sorted_sections = dict(sorted(sections.items(), key=lambda x: sort_key(x[0])))
    return render_template('sales/counter_sale.html', sections=sorted_sections, class_options=CLASS_OPTIONS)



@sales.route('/bill/<int:bill_id>')
@login_required
@store_staff_required
def view_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    if bill.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('sales.counter_sale'))
    return render_template('sales/bill.html', bill=bill)


@sales.route('/bill/<int:bill_id>/download')
@login_required
@store_staff_required
def download_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    if bill.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('sales.counter_sale'))

    pdf_buffer = generate_bill_pdf(bill)
    return send_file(pdf_buffer, as_attachment=True, download_name=f'{bill.bill_number}.pdf', mimetype='application/pdf')

@sales.route('/bill/<int:bill_id>/view-pdf')
@login_required
@store_staff_required
def view_bill_pdf(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    if bill.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('sales.counter_sale'))

    pdf_buffer = generate_bill_pdf(bill)
    return send_file(pdf_buffer, as_attachment=False, download_name=f'{bill.bill_number}.pdf', mimetype='application/pdf')


@sales.route('/history')
@login_required
@store_staff_required
def bill_history():
    city_id = get_active_city_id()

    date_str = request.args.get('date')
    if date_str:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        selected_date = date.today()

    start = datetime(selected_date.year, selected_date.month, selected_date.day, 0, 0, 0)
    end = datetime(selected_date.year, selected_date.month, selected_date.day, 23, 59, 59)

    all_bills = Bill.query.filter_by(city_id=city_id).filter(
        Bill.created_at >= start, Bill.created_at <= end
    ).order_by(Bill.created_at.desc()).all()

    return render_template('sales/history.html', bills=all_bills, selected_date=selected_date)


@sales.route('/collect', methods=['GET', 'POST'])
@login_required
@store_staff_required
def collect_otp():
    city_id = get_active_city_id()

    if request.method == 'POST':
        otp_code = request.form.get('otp_code', '').strip()

        order = Order.query.filter_by(otp_code=otp_code, city_id=city_id).first()

        if not order:
            flash('Invalid OTP or order not found for your active school')
            return redirect(url_for('sales.collect_otp'))

        if order.status == 'collected':
            flash('This OTP has already been used — order already collected')
            return redirect(url_for('sales.collect_otp'))

        if order.status == 'cancelled':
            flash('This order was cancelled')
            return redirect(url_for('sales.collect_otp'))

        for item in order.items:
            product = Product.query.get(item.product_id)
            if not product:
                flash(f'Product "{item.product_name}" no longer exists — contact Super Admin')
                return redirect(url_for('sales.collect_otp'))

        from app.models import City
        active_city = City.query.get(order.city_id)

        new_bill = Bill(
            bill_number=generate_bill_number(active_city),
            sale_type='online',
            city_id=order.city_id,
            created_by_id=current_user.id,
            buyer_name=order.parent_name,
            buyer_phone=order.parent_phone,
            student_name=order.student_name,
            student_class=order.student_class,
            admission_number=order.admission_number,
            payment_method=order.payment_method,
            total_amount=order.total_amount
        )
        db.session.add(new_bill)
        db.session.flush()

        for item in order.items:
            product = Product.query.get(item.product_id)
            bill_item = BillItem(
                bill_id=new_bill.id,
                product_id=product.id,
                product_name=product.name,
                publisher_name=product.publisher_name,
                subject=product.subject,
                hsn_number=product.hsn_number,
                gst_percent=product.gst_percent,
                is_gst_exempt=product.is_gst_exempt,
                price=item.price,
                quantity=item.quantity,
                subtotal=item.subtotal
            )
            db.session.add(bill_item)
            # stock already deducted at payment time — not deducted again here

        order.status = 'collected'
        order.collected_at = datetime.utcnow()
        order.bill_id = new_bill.id

        db.session.commit()

        log_activity('Collected OTP / generated bill', f'Bill {new_bill.bill_number} for {order.student_name}')
        flash(f'Order collected successfully — Bill {new_bill.bill_number} generated')
        return redirect(url_for('sales.view_bill', bill_id=new_bill.id))

    pending_orders = Order.query.filter_by(city_id=city_id, status='pending').order_by(Order.created_at.desc()).all()
    return render_template('sales/collect_otp.html', pending_orders=pending_orders)




@sales.route('/issuances')
@login_required
@store_staff_required
def issuance_log():
    city_id = get_active_city_id()
    records = Issuance.query.filter_by(city_id=city_id).order_by(Issuance.issued_at.desc()).all()
    products = Product.query.filter_by(city_id=city_id, is_active=True).order_by(Product.name).all()
    return render_template('sales/issuances.html', records=records, products=products)


@sales.route('/issuances/record', methods=['POST'])
@login_required
@store_staff_required
def record_issuance():
    city_id = get_active_city_id()

    teacher_name = request.form.get('teacher_name', '').strip()
    teacher_employee_id = request.form.get('teacher_employee_id', '').strip() or None
    product_id = request.form.get('product_id')
    quantity = request.form.get('quantity', '').strip()
    issue_date_str = request.form.get('issue_date', '').strip()
    notes = request.form.get('notes', '').strip() or None

    if not teacher_name or not product_id or not quantity:
        flash('Teacher name, item and quantity are required')
        return redirect(url_for('sales.issuance_log'))

    try:
        quantity = int(quantity)
    except ValueError:
        flash('Quantity must be a number')
        return redirect(url_for('sales.issuance_log'))

    product = Product.query.get(int(product_id))
    if not product or product.city_id != city_id or not product.is_active:
        flash('Invalid product selected')
        return redirect(url_for('sales.issuance_log'))

    if product.stock_quantity < quantity:
        flash(f'Not enough stock for "{product.name}" (available: {product.stock_quantity})')
        return redirect(url_for('sales.issuance_log'))

    if issue_date_str:
        try:
            issued_at = datetime.strptime(issue_date_str, '%Y-%m-%d')
        except ValueError:
            issued_at = datetime.utcnow()
    else:
        issued_at = datetime.utcnow()

    issuance = Issuance(
        teacher_name=teacher_name,
        teacher_employee_id=teacher_employee_id,
        recorded_by_id=current_user.id,
        city_id=city_id,
        product_id=product.id,
        product_name=product.name,
        quantity=quantity,
        notes=notes,
        issued_at=issued_at
    )
    product.stock_quantity -= quantity
    db.session.add(issuance)
    db.session.commit()

    flash(f'Recorded: issued {quantity} x "{product.name}" to {teacher_name}')
    return redirect(url_for('sales.issuance_log'))

@sales.route('/issuances/<int:issuance_id>/return', methods=['POST'])
@login_required
@store_staff_required
def return_issuance(issuance_id):
    issuance = Issuance.query.get_or_404(issuance_id)
    city_id = get_active_city_id()

    if issuance.city_id != city_id:
        flash('Access denied')
        return redirect(url_for('sales.issuance_log'))

    if issuance.status == 'returned':
        flash('This item was already marked as returned')
        return redirect(url_for('sales.issuance_log'))

    issuance.status = 'returned'
    issuance.returned_at = datetime.utcnow()

    if issuance.product_id:
        product = Product.query.get(issuance.product_id)
        if product:
            product.stock_quantity += issuance.quantity

    db.session.commit()
    flash(f'Marked "{issuance.product_name}" as returned to store')
    return redirect(url_for('sales.issuance_log'))

@sales.route('/bill/<int:bill_id>/delete', methods=['POST'])
@login_required
@store_staff_required
def delete_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)

    if bill.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('sales.bill_history'))

    for item in list(bill.items):
        db.session.delete(item)

    if bill.source_order:
        for order in bill.source_order:
            order.bill_id = None

    bill_number = bill.bill_number
    db.session.delete(bill)
    db.session.commit()

    flash(f'Bill {bill_number} deleted')
    return redirect(url_for('sales.bill_history'))

@sales.route('/bill/<int:bill_id>/download-excel')
@login_required
@store_staff_required
def download_bill_excel(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    if bill.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('sales.counter_sale'))

    excel_buffer = generate_bill_excel(bill)
    return send_file(
        excel_buffer,
        as_attachment=True,
        download_name=f'{bill.bill_number}.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@sales.route('/bill/<int:bill_id>/print')
@login_required
@store_staff_required
def print_bill_three_copies(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    if bill.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('sales.counter_sale'))

    pdf_buffer = generate_bill_pdf_three_copies(bill)
    return send_file(pdf_buffer, as_attachment=False, download_name=f'{bill.bill_number}_3copies.pdf', mimetype='application/pdf')

@sales.route('/coupons', methods=['GET', 'POST'])
@login_required
@store_staff_required
def coupon_collect():
    city_id = get_active_city_id()

    if request.method == 'POST':
        otp_code = request.form.get('otp_code', '').strip()

        coupon = CouponOrder.query.filter_by(otp_code=otp_code, city_id=city_id).first()

        if not coupon:
            flash('Invalid OTP or coupon not found for your active school')
            return redirect(url_for('sales.coupon_collect'))

        if coupon.status == 'collected':
            flash('This coupon OTP has already been used')
            return redirect(url_for('sales.coupon_collect'))

        coupon.status = 'collected'
        coupon.collected_at = datetime.utcnow()
        coupon.collected_by_id = current_user.id
        db.session.commit()

        flash(f'Coupon of ₹{coupon.amount:.0f} collected for {coupon.student_name}')
        return redirect(url_for('sales.coupon_collect'))

    all_coupons = CouponOrder.query.filter_by(city_id=city_id).order_by(CouponOrder.created_at.desc()).all()
    total_amount = sum(c.amount for c in all_coupons if c.status == 'collected')
    return render_template('sales/coupons.html', coupons=all_coupons, total_amount=total_amount)

@sales.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
@store_staff_required
def cancel_order(order_id):
    order = Order.query.get_or_404(order_id)
    city_id = get_active_city_id()

    if order.city_id != city_id:
        flash('Access denied')
        return redirect(url_for('sales.collect_otp'))

    if order.status == 'collected':
        flash('This order has already been collected — cannot cancel')
        return redirect(url_for('sales.collect_otp'))

    if order.status == 'cancelled':
        flash('This order is already cancelled')
        return redirect(url_for('sales.collect_otp'))

    # restore the stock that was deducted at payment time
    for item in order.items:
        product = Product.query.get(item.product_id)
        if product:
            product.stock_quantity += item.quantity

    order.status = 'cancelled'
    db.session.commit()

    log_activity('Cancelled order', f'Order {order.order_number}')
    flash(f'Order {order.order_number} cancelled — stock restored')
    return redirect(url_for('sales.collect_otp'))

@sales.route('/orders/<int:order_id>/print')
@login_required
@store_staff_required
def print_order_items(order_id):
    order = Order.query.get_or_404(order_id)
    city_id = get_active_city_id()

    if order.city_id != city_id:
        flash('Access denied')
        return redirect(url_for('sales.collect_otp'))

    return render_template('sales/print_order_items.html', order=order)

@sales.route('/buy-bundle')
@login_required
@store_staff_required
def buy_bundle_lookup():
    return render_template('sales/buy_bundle_lookup.html', class_options=CLASS_OPTIONS)


@sales.route('/buy-bundle/confirm', methods=['POST'])
@login_required
@store_staff_required
def buy_bundle_confirm():
    city_id = get_active_city_id()
    admission_number = request.form.get('admission_number', '').strip()
    student_name = request.form.get('student_name', '').strip()
    student_class = normalize_class_value(request.form.get('student_class', '')) or ''

    if not admission_number or not student_name or not student_class:
        flash('Student not found — please search again')
        return redirect(url_for('sales.buy_bundle_lookup'))

    if needs_stream(student_class):
        stream = request.form.get('stream', '')
        if stream not in dict(STREAM_OPTIONS):
            return render_template('sales/buy_bundle_stream.html', admission_number=admission_number,
                                    student_name=student_name, student_class=student_class, streams=STREAM_OPTIONS)
        student_class = f'{student_class}-{stream}'

    mode = 'custom' if request.form.get('mode') == 'custom' else 'whole'

    def add_line_total(entry):
        product = entry['product']
        gst_amount = 0.0 if product.is_gst_exempt else round(product.price * entry['quantity'] * product.gst_percent / 100, 2)
        entry['line_total'] = product.price * entry['quantity'] + gst_amount
        return entry

    if mode == 'custom':
        shop = get_custom_shop_items(city_id, student_class)
        compulsory_items = [add_line_total(e) for e in shop['compulsory']]
        elective_items = [add_line_total(e) for e in shop['electives']]
        optional_items = [add_line_total(e) for e in shop['optional']]
        blocked = [e['product'].name for e in compulsory_items if not e['in_stock']]
        return render_template('sales/buy_bundle_confirm.html', admission_number=admission_number,
                                student_name=student_name, student_class=student_class, mode=mode,
                                compulsory_items=compulsory_items, elective_items=elective_items,
                                optional_items=optional_items, optional_groups=group_by_section(optional_items, student_class),
                                blocked=blocked,
                                compulsory_total=round(sum(e['line_total'] for e in compulsory_items), 2))

    bundle = Bundle.query.filter_by(city_id=city_id, applicable_class=student_class).first()

    compulsory_items = []
    elective_items = []
    compulsory_total = 0.0

    if bundle:
        for bi in bundle.items:
            product = bi.product
            if not product or not product.is_active:
                continue
            gst_amount = 0.0 if product.is_gst_exempt else round(product.price * bi.quantity * product.gst_percent / 100, 2)
            line_total = product.price * bi.quantity + gst_amount
            entry = {'product': product, 'quantity': bi.quantity, 'line_total': line_total}
            if product.is_elective:
                elective_items.append(entry)
            else:
                compulsory_items.append(entry)
                compulsory_total += line_total

    return render_template('sales/buy_bundle_confirm.html', admission_number=admission_number,
                            student_name=student_name, student_class=student_class, mode=mode,
                            compulsory_items=compulsory_items, elective_items=elective_items,
                            optional_items=[], optional_groups=[], blocked=[],
                            compulsory_total=round(compulsory_total, 2))


@sales.route('/buy-bundle/generate', methods=['POST'])
@login_required
@store_staff_required
def buy_bundle_generate():
    city_id = get_active_city_id()

    admission_number = request.form.get('admission_number', '').strip()
    student_name = request.form.get('student_name', '').strip()
    student_class = normalize_class_value(request.form.get('student_class', '')) or ''
    buyer_name = request.form.get('buyer_name', '').strip()
    buyer_phone = request.form.get('buyer_phone', '').strip()
    payment_method = request.form.get('payment_method', '').strip()
    mode = 'custom' if request.form.get('mode') == 'custom' else 'whole'

    def ids_from(field):
        out = set()
        for v in request.form.getlist(field):
            try:
                out.add(int(v))
            except ValueError:
                pass
        return out

    selected_elective_ids = ids_from('elective_product_id')
    selected_optional_ids = ids_from('optional_product_id')

    if not all([admission_number, student_name, student_class, buyer_name, buyer_phone, payment_method]):
        flash('All fields are required')
        return redirect(url_for('sales.buy_bundle_lookup'))

    products_map = {}
    if mode == 'custom':
        shop = get_custom_shop_items(city_id, student_class)
        for group, chosen in ((shop['compulsory'], None), (shop['electives'], selected_elective_ids), (shop['optional'], selected_optional_ids)):
            for e in group:
                product = e['product']
                if chosen is not None and product.id not in chosen:
                    continue
                if product.stock_quantity < e['quantity']:
                    flash(f'Not enough stock for "{product.name}" (available: {product.stock_quantity})')
                    return redirect(url_for('sales.buy_bundle_lookup'))
                products_map[product.id] = (product, e['quantity'])
    else:
        bundle = Bundle.query.filter_by(city_id=city_id, applicable_class=student_class).first()
        if not bundle or not bundle.items:
            flash('No bundle found for this class')
            return redirect(url_for('sales.buy_bundle_lookup'))

        for bi in bundle.items:
            product = bi.product
            if not product or product.city_id != city_id or not product.is_active:
                continue
            if product.is_elective and product.id not in selected_elective_ids:
                continue
            if product.stock_quantity < bi.quantity:
                flash(f'Not enough stock for "{product.name}" (available: {product.stock_quantity})')
                return redirect(url_for('sales.buy_bundle_lookup'))
            products_map[bi.product_id] = (product, bi.quantity)

    if not products_map:
        flash('No valid items in this bundle')
        return redirect(url_for('sales.buy_bundle_lookup'))

    from app.models import City
    active_city = City.query.get(city_id)
    new_bill = Bill(
        bill_number=generate_bill_number(active_city),
        sale_type='offline',
        city_id=city_id,
        created_by_id=current_user.id,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        student_name=student_name,
        student_class=student_class,
        admission_number=admission_number,
        payment_method=payment_method,
        total_amount=0.0
    )
    db.session.add(new_bill)
    db.session.flush()

    total = 0.0
    for product, qty in products_map.values():
        subtotal = product.price * qty
        gst_amount = 0.0 if product.is_gst_exempt else round(subtotal * product.gst_percent / 100, 2)
        line_total = subtotal + gst_amount

        item = BillItem(
            bill_id=new_bill.id,
            product_id=product.id,
            product_name=product.name,
            publisher_name=product.publisher_name,
            subject=product.subject,
            hsn_number=product.hsn_number,
            gst_percent=product.gst_percent,
            is_gst_exempt=product.is_gst_exempt,
            price=product.price,
            quantity=qty,
            subtotal=subtotal
        )
        db.session.add(item)

        product.stock_quantity -= qty
        total += line_total

    new_bill.total_amount = total
    db.session.commit()

    flash(f'{"Custom bundle" if mode == "custom" else "Bundle"} bill {new_bill.bill_number} generated successfully')
    return redirect(url_for('sales.view_bill', bill_id=new_bill.id))
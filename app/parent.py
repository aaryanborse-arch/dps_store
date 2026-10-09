import random
import string
from flask import jsonify
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from app import db
from app.models import City, Product, Order, OrderItem
from app.class_options import CLASS_OPTIONS, normalize_class_value, needs_stream, STREAM_OPTIONS
from app.models import Bundle
from app.pdf_utils import to_roman
from flask import jsonify
from app.models import StudentRecord
import os
import base64
import json
import requests
from app.models import PendingJodoOrder
from app.bundle_rules import get_custom_shop_items

parent = Blueprint('parent', __name__, url_prefix='/shop')
JODO_LINK = "https://pay.jodo.in/pages/ddHuKHxLyAfQP7SY"


def send_otp_email(to_email, student_name, school_name, otp_code, order_number):
    brevo_api_key = os.environ.get('BREVO_API_KEY')
    sender_email = os.environ.get('BREVO_SENDER_EMAIL')

    if not brevo_api_key or not sender_email or not to_email:
        print("OTP EMAIL SKIPPED — missing API key, sender, or recipient email")
        return

    payload = {
        "sender": {"name": "DPS School Store", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": f"Your OTP for {school_name} School Store — Order {order_number}",
        "htmlContent": f"""
            <div style="font-family: Arial, sans-serif; max-width: 480px; margin: auto;">
                <h2 style="color: #B5651D;">{school_name} School Store</h2>
                <p>Your payment for <strong>{student_name}</strong> was successful.</p>
                <p>Please show this OTP at the store counter to collect your items:</p>
                <h1 style="text-align: center; letter-spacing: 4px; color: #1E7A46;">{otp_code}</h1>
                <p style="color: #777; font-size: 13px;">Order Number: {order_number}</p>
            </div>
        """
    }

    try:
        response = requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={
                'api-key': brevo_api_key,
                'Content-Type': 'application/json',
                'accept': 'application/json'
            },
            json=payload,
            timeout=10
        )
        print(f"OTP EMAIL — status={response.status_code}, response={response.text}")
    except Exception as e:
        print(f"OTP EMAIL ERROR: {e}")


def generate_order_number():
    date_part = datetime.utcnow().strftime('%Y%m%d')
    rand_part = ''.join(random.choices(string.digits, k=4))
    return f'ORD-{date_part}-{rand_part}'


def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


@parent.route('/')
def select_city():
    session['cart'] = {}  # fresh start when picking a city
    cities = City.query.filter_by(is_active=True).order_by(City.name).all()
    return render_template('parent/select_city.html', cities=cities)


@parent.route('/city/<int:city_id>/class', methods=['GET', 'POST'])
def select_class(city_id):
    city = City.query.get_or_404(city_id)

    if request.method == 'POST':
        student_class = request.form.get('student_class', '').strip()
        student_name = request.form.get('student_name', '').strip()
        admission_number = request.form.get('admission_number', '').strip()

        if not student_class or not student_name or not admission_number:
            flash('Student not found — please search your Admission Number again')
            return redirect(url_for('parent.select_class', city_id=city_id))

        session['shop_city_id'] = city_id
        session['shop_student_name'] = student_name
        session['shop_admission_number'] = admission_number
        normalized_class = normalize_class_value(student_class)
        if needs_stream(normalized_class):
            session.pop('shop_class', None)
            session['shop_class_base'] = normalized_class
            return redirect(url_for('parent.select_stream'))
        session['shop_class'] = normalized_class
        return redirect(url_for('parent.purchase_choice'))

    return render_template('parent/select_class.html', city=city)


@parent.route('/select-stream', methods=['GET', 'POST'])
def select_stream():
    city_id = session.get('shop_city_id')
    base_class = session.get('shop_class_base')
    if not city_id or not needs_stream(base_class):
        return redirect(url_for('parent.select_city'))

    if request.method == 'POST':
        stream = request.form.get('stream', '')
        if stream not in dict(STREAM_OPTIONS):
            flash('Please choose a stream')
            return redirect(url_for('parent.select_stream'))
        session['shop_class'] = f'{base_class}-{stream}'
        return redirect(url_for('parent.purchase_choice'))

    city = City.query.get_or_404(city_id)
    return render_template('parent/select_stream.html', city=city, base_class=base_class,
                            streams=STREAM_OPTIONS, student_name=session.get('shop_student_name', ''))

@parent.route('/purchase-choice')
def purchase_choice():
    city_id = session.get('shop_city_id')
    if not city_id or not session.get('shop_class'):
        return redirect(url_for('parent.select_city'))
    session['cart'] = {}
    city = City.query.get_or_404(city_id)
    return render_template('parent/purchase_choice.html', city=city)

@parent.route('/browse', methods=['GET', 'POST'])
def browse():
    city_id = session.get('shop_city_id')
    student_class = session.get('shop_class')
    if not city_id or not student_class:
        return redirect(url_for('parent.select_city'))

    city = City.query.get_or_404(city_id)
    shop = get_custom_shop_items(city_id, student_class)
    blocked = [e['product'].name for e in shop['compulsory'] if not e['in_stock']]

    if request.method == 'POST':
        if blocked:
            flash('Sorry, these compulsory items are out of stock right now: ' + ', '.join(blocked) + '. Please try again later or contact the store.')
            return redirect(url_for('parent.browse'))

        def ids_from(field):
            out = set()
            for v in request.form.getlist(field):
                try:
                    out.add(int(v))
                except ValueError:
                    pass
            return out

        chosen_electives = ids_from('elective_product_id')
        chosen_optional = ids_from('optional_product_id')

        cart = {}
        for e in shop['compulsory']:
            cart[str(e['product'].id)] = e['quantity']
        for group, chosen in ((shop['electives'], chosen_electives), (shop['optional'], chosen_optional)):
            for e in group:
                if e['product'].id in chosen:
                    if not e['in_stock']:
                        flash(f'"{e["product"].name}" is out of stock right now — please untick it')
                        return redirect(url_for('parent.browse'))
                    cart[str(e['product'].id)] = e['quantity']

        if not cart:
            flash('Please select at least one item')
            return redirect(url_for('parent.browse'))

        session['cart'] = cart
        session['checkout_source'] = 'custom'
        session['locked_ids'] = [e['product'].id for e in shop['compulsory']]
        flash('Cart updated')
        return redirect(url_for('parent.view_cart'))

    cart = session.get('cart', {})
    return render_template('parent/browse.html', city=city, student_class=student_class,
                            compulsory=shop['compulsory'], electives=shop['electives'],
                            optional_items=shop['optional'], blocked=blocked, cart=cart)

@parent.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    qty = int(request.form.get('quantity', 1))

    cart = session.get('cart', {})
    key = str(product_id)
    cart[key] = cart.get(key, 0) + qty
    session['cart'] = cart
    flash(f'Added {product.name} to cart')
    return redirect(url_for('parent.browse'))


@parent.route('/cart')
def view_cart():
    cart = session.get('cart', {})
    items = []
    total = 0.0
    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if product:
            subtotal = product.price * qty
            items.append({'product': product, 'quantity': qty, 'subtotal': subtotal})
            total += subtotal
    locked_ids = set(session.get('locked_ids', [])) if session.get('checkout_source') == 'custom' else set()
    return render_template('parent/cart.html', items=items, total=total, locked_ids=locked_ids)


@parent.route('/cart/remove/<int:product_id>', methods=['POST'])
def remove_from_cart(product_id):
    if session.get('checkout_source') == 'custom' and product_id in set(session.get('locked_ids', [])):
        flash('This item is compulsory for your class and cannot be removed')
        return redirect(url_for('parent.view_cart'))
    cart = session.get('cart', {})
    cart.pop(str(product_id), None)
    session['cart'] = cart
    return redirect(url_for('parent.view_cart'))


@parent.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty')
        return redirect(url_for('parent.select_city'))

    if request.method == 'POST':
        parent_name = request.form.get('parent_name', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        student_name = request.form.get('student_name', '').strip()
        admission_number = request.form.get('admission_number', '').strip()
        payment_method = request.form.get('payment_method', '').strip()
        student_class = session.get('shop_class')
        city_id = session.get('shop_city_id')

        if not all([parent_name, parent_phone, parent_email, student_name, admission_number, payment_method, student_class, city_id]):
            flash('All fields are required, including Email and Payment Method')
            return redirect(url_for('parent.checkout'))

        items_data = []
        total = 0.0
        for pid, qty in cart.items():
            product = Product.query.get(int(pid))
            if not product or not product.is_active or product.city_id != int(city_id):
                flash('One of your cart items is no longer available')
                return redirect(url_for('parent.view_cart'))
            if product.stock_quantity < qty:
                flash(f'Not enough stock for "{product.name}"')
                return redirect(url_for('parent.view_cart'))
            subtotal = product.price * qty
            gst_amount = 0.0 if product.is_gst_exempt else round(subtotal * product.gst_percent / 100, 2)
            line_total = subtotal + gst_amount
            items_data.append((product, qty, subtotal))
            total += line_total

        pending = PendingJodoOrder(
            city_id=int(city_id),
            parent_name=parent_name,
            parent_phone=parent_phone,
            parent_email=parent_email,
            student_name=student_name,
            student_class=student_class,
            admission_number=admission_number,
            payment_method=payment_method,
            cart_snapshot=json.dumps(cart),
            total_amount=total,
            status='pending'
        )
        db.session.add(pending)
        db.session.commit()

        base_url = os.environ.get('JODO_BASE_URL')
        api_key = os.environ.get('JODO_API_KEY')
        api_secret = os.environ.get('JODO_API_SECRET')
        auth_string = base64.b64encode(f'{api_key}:{api_secret}'.encode()).decode()

        payload = {
            'name': parent_name,
            'phone': parent_phone,
            'email': parent_email,
            'student_name': student_name,
            'identifier': admission_number,
            'details': [
                {'component_type': 'Payable Amount', 'amount': round(total, 2)}
            ]
        }

        try:
            response = requests.post(
                f'{base_url}/api/v1/integrations/pay/payment_links',
                headers={
                    'Authorization': f'Basic {auth_string}',
                    'Content-Type': 'application/json'
                },
                json=payload,
                timeout=15
            )
            data = response.json()

            if response.status_code == 201 and data.get('status') == 'success':
                jodo_order_id = data['data']['order_id']
                redirect_url = data['data']['redirect_url']

                pending.jodo_order_id = jodo_order_id
                db.session.commit()

                session['cart'] = {}
                session['tracking_pending_id'] = pending.id

                return redirect(redirect_url)
            else:
                flash('Could not start payment — please try again')
                return redirect(url_for('parent.checkout'))

        except Exception as e:
            print(f"JODO API ERROR: {e}")
            flash(f'Could not connect to the payment gateway — please try again (debug: {e})')
            return redirect(url_for('parent.checkout'))

    return render_template('parent/checkout.html', cart_count=len(cart),
                            student_name=session.get('shop_student_name', ''),
                            admission_number=session.get('shop_admission_number', ''))

@parent.route('/checkout/confirm-payment', methods=['POST'])
def confirm_order_payment():
    pending = session.get('pending_order')
    if not pending:
        flash('Your session expired — please start again')
        return redirect(url_for('parent.select_city'))

    city_id = pending['city_id']
    cart = pending['cart_snapshot']

    # re-validate stock at confirm time, in case anything changed while they were on Jodo's page
    items_data = []
    total = 0.0
    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or not product.is_active or product.city_id != city_id:
            flash('One of your cart items is no longer available — please review your cart again')
            session.pop('pending_order', None)
            return redirect(url_for('parent.view_cart'))
        if product.stock_quantity < qty:
            flash(f'Not enough stock for "{product.name}" — please review your cart again')
            session.pop('pending_order', None)
            return redirect(url_for('parent.view_cart'))
        subtotal = product.price * qty
        gst_amount = 0.0 if product.is_gst_exempt else round(subtotal * product.gst_percent / 100, 2)
        line_total = subtotal + gst_amount
        items_data.append((product, qty, subtotal))
        total += line_total

    for product, qty, subtotal in items_data:
        product.stock_quantity -= qty

    otp = generate_otp()
    new_order = Order(
        order_number=generate_order_number(),
        otp_code=otp,
        status='pending',
        city_id=city_id,
        parent_name=pending['parent_name'],
        parent_phone=pending['parent_phone'],
        student_name=pending['student_name'],
        student_class=pending['student_class'],
        admission_number=pending['admission_number'],
        payment_method=pending['payment_method'],
        buyer_state=pending['buyer_state'],
        total_amount=total
    )
    db.session.add(new_order)
    db.session.flush()

    for product, qty, subtotal in items_data:
        item = OrderItem(
            order_id=new_order.id,
            product_id=product.id,
            product_name=product.name,
            price=product.price,
            quantity=qty,
            subtotal=subtotal
        )
        db.session.add(item)

    db.session.commit()

    session['cart'] = {}
    session.pop('pending_order', None)

    return render_template('parent/order_success.html', order=new_order)

@parent.route('/bundle')
def bundle_view():
    city_id = session.get('shop_city_id')
    student_class = session.get('shop_class')
    if not city_id or not student_class:
        return redirect(url_for('parent.select_city'))

    city = City.query.get_or_404(city_id)
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

    # split compulsory items into sections (Textbooks, Common Items, Stationary, Notebook) for parents
    def section_of(product):
        if product.applicable_class == student_class:
            return 'Textbooks'
        if product.applicable_class is None:
            return 'Common Items'
        if product.applicable_class in ('extra', 'stationary'):
            return 'Stationary'
        if product.applicable_class == 'notebook':
            return 'Notebook'
        return 'Other Items'

    section_names = ['Textbooks', 'Common Items', 'Stationary', 'Notebook', 'Other Items']
    section_entries = {name: [] for name in section_names}
    for entry in compulsory_items:
        section_entries[section_of(entry['product'])].append(entry)

    compulsory_sections = []
    for name in section_names:
        grouped_compulsory = {}
        order = []
        singles = []
        for entry in sorted(section_entries[name], key=lambda e: e['product'].name.lower()):
            product = entry['product']
            if product.subject:
                if product.subject not in grouped_compulsory:
                    grouped_compulsory[product.subject] = {'subject': product.subject, 'names': [], 'line_total': 0.0}
                    order.append(product.subject)
                grouped_compulsory[product.subject]['names'].append(product.name)
                grouped_compulsory[product.subject]['line_total'] += entry['line_total']
            else:
                singles.append(entry)
        rows = [grouped_compulsory[s] for s in order] + singles
        if rows:
            compulsory_sections.append({
                'title': name,
                'rows': rows,
                'total': round(sum(e['line_total'] for e in section_entries[name]), 2),
            })
    compulsory_display = [row for section in compulsory_sections for row in section['rows']]

    return render_template('parent/bundle_view.html', city=city, student_class=student_class,
                            student_class_label=to_roman(student_class),
                            compulsory_display=compulsory_display, compulsory_sections=compulsory_sections,
                            elective_items=elective_items,
                            compulsory_total=round(compulsory_total, 2))

@parent.route('/bundle/checkout-start', methods=['POST'])
def bundle_checkout_start():
    city_id = session.get('shop_city_id')
    student_class = session.get('shop_class')
    if not city_id or not student_class:
        return redirect(url_for('parent.select_city'))

    bundle = Bundle.query.filter_by(city_id=city_id, applicable_class=student_class).first()
    if not bundle or not bundle.items:
        flash('No bundle has been set up for this class yet — please contact the store.')
        return redirect(url_for('parent.bundle_view'))

    selected_elective_ids = set(int(i) for i in request.form.getlist('elective_product_id'))

    cart = {}
    for bi in bundle.items:
        product = bi.product
        if not product or not product.is_active:
            continue
        if product.is_elective and product.id not in selected_elective_ids:
            continue
        cart[str(bi.product_id)] = bi.quantity

    if not cart:
        flash('Please select your bundle items before proceeding')
        return redirect(url_for('parent.bundle_view'))

    session['cart'] = cart
    session['checkout_source'] = 'bundle'
    return redirect(url_for('parent.direct_jodo_checkout'))

import re

def normalize_admission_text(value):
    if not value:
        return ''
    value = str(value).strip().upper()
    value = re.sub(r'[\s\u200B-\u200D\uFEFF\u00A0]+', '', value)
    return value


@parent.route('/lookup-student')
def lookup_student():
    city_id = request.args.get('city_id')
    admission_number = request.args.get('admission_number', '').strip()
    if not city_id or not admission_number:
        return jsonify({'found': False})

    wanted = normalize_admission_text(admission_number)
    all_records = StudentRecord.query.filter_by(city_id=int(city_id)).all()

    for record in all_records:
        if normalize_admission_text(record.admission_number) == wanted:
            return jsonify({'found': True, 'name': record.student_name, 'student_class': record.student_class})

    return jsonify({'found': False})

@parent.route('/jodo/webhook', methods=['POST'])
def jodo_webhook():
    payload = request.get_json(silent=True) or {}
    print(f"JODO WEBHOOK RECEIVED — FULL PAYLOAD: {payload}")

    event = payload.get('event', '')
    order_data = payload.get('payload', {})
    jodo_order_id = order_data.get('order_id')

    if not jodo_order_id:
        print(f"JODO WEBHOOK — no order_id found in payload")
        return jsonify({'status': 'ignored'}), 200

    pending = PendingJodoOrder.query.filter_by(jodo_order_id=jodo_order_id).first()
    if not pending:
        print(f"JODO WEBHOOK — no matching pending order for jodo_order_id={jodo_order_id}")
        return jsonify({'status': 'ignored'}), 200
    if pending.status != 'pending':
        print(f"JODO WEBHOOK — order already processed, status={pending.status}")
        return jsonify({'status': 'ignored'}), 200

    order_status = order_data.get('order', {}).get('status', '')
    print(f"JODO WEBHOOK — event={event}, order_status={order_status}")

    if order_status == 'paid':
        cart = json.loads(pending.cart_snapshot)

        items_data = []
        total = 0.0
        for pid, qty in cart.items():
            product = Product.query.get(int(pid))
            if not product or product.stock_quantity < qty:
                pending.status = 'failed'
                db.session.commit()
                return jsonify({'status': 'error', 'reason': 'stock unavailable'}), 200
            subtotal = product.price * qty
            gst_amount = 0.0 if product.is_gst_exempt else round(subtotal * product.gst_percent / 100, 2)
            items_data.append((product, qty, subtotal))
            total += subtotal + gst_amount

        for product, qty, subtotal in items_data:
            product.stock_quantity -= qty

        otp = generate_otp()
        new_order = Order(
            order_number=generate_order_number(),
            otp_code=otp,
            status='pending',
            city_id=pending.city_id,
            parent_name=pending.parent_name,
            parent_phone=pending.parent_phone,
            student_name=pending.student_name,
            student_class=pending.student_class,
            admission_number=pending.admission_number,
            payment_method=pending.payment_method,
            total_amount=total
        )
        db.session.add(new_order)
        db.session.flush()

        for product, qty, subtotal in items_data:
            item = OrderItem(
                order_id=new_order.id,
                product_id=product.id,
                product_name=product.name,
                price=product.price,
                quantity=qty,
                subtotal=subtotal
            )
            db.session.add(item)

        pending.status = 'completed'
        pending.resulting_order_id = new_order.id
        db.session.commit()

        city = City.query.get(pending.city_id)
        send_otp_email(
            to_email=pending.parent_email,
            student_name=pending.student_name,
            school_name=city.name if city else 'DPS',
            otp_code=otp,
            order_number=new_order.order_number
        )

        return jsonify({'status': 'ok'}), 200
        return jsonify({'status': 'ok'}), 200

    return jsonify({'status': 'ignored'}), 200

@parent.route('/checkout/direct', methods=['GET', 'POST'])
def direct_jodo_checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('Your cart is empty')
        return redirect(url_for('parent.select_city'))

    student_name = session.get('shop_student_name', '')
    admission_number = session.get('shop_admission_number', '')
    student_class = session.get('shop_class')
    city_id = session.get('shop_city_id')

    if not all([student_name, admission_number, student_class, city_id]):
        flash('Session expired — please start again')
        return redirect(url_for('parent.select_city'))

    if session.get('checkout_source') == 'custom':
        shop = get_custom_shop_items(city_id, student_class)
        for e in shop['compulsory']:
            if cart.get(str(e['product'].id), 0) < e['quantity']:
                flash(f'"{e["product"].name}" is compulsory for this class — please review your selection')
                return redirect(url_for('parent.browse'))

    if request.method == 'GET':
        return render_template('parent/quick_checkout_details.html')

    parent_name = request.form.get('parent_name', '').strip()
    parent_phone = request.form.get('parent_phone', '').strip()
    parent_email = request.form.get('parent_email', '').strip()

    if not parent_name or not parent_phone or not parent_email:
        flash('Please fill in all fields')
        return redirect(url_for('parent.direct_jodo_checkout'))

    items_data = []
    total = 0.0
    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product or not product.is_active or product.city_id != int(city_id):
            flash('One of your cart items is no longer available')
            return redirect(url_for('parent.bundle_view') if session.get('checkout_source') == 'bundle' else url_for('parent.view_cart'))
        if product.stock_quantity < qty:
            flash(f'Not enough stock for "{product.name}"')
            return redirect(url_for('parent.bundle_view') if session.get('checkout_source') == 'bundle' else url_for('parent.view_cart'))
        subtotal = product.price * qty
        gst_amount = 0.0 if product.is_gst_exempt else round(subtotal * product.gst_percent / 100, 2)
        items_data.append((product, qty, subtotal))
        total += subtotal + gst_amount

    city = City.query.get(int(city_id))
    if not city or not city.jodo_component_code:
        flash('Online payment is not yet configured for this school — please contact the store.')
        return redirect(url_for('parent.bundle_view') if session.get('checkout_source') == 'bundle' else url_for('parent.view_cart'))   

    pending = PendingJodoOrder(
        city_id=int(city_id),
        parent_name=parent_name,
        parent_phone=parent_phone,
        parent_email=parent_email,
        student_name=student_name,
        student_class=student_class,
        admission_number=admission_number,
        payment_method='Online',
        cart_snapshot=json.dumps(cart),
        total_amount=total,
        status='pending'
    )
    db.session.add(pending)
    db.session.commit()

    base_url = os.environ.get('JODO_BASE_URL')
    api_key = os.environ.get('JODO_API_KEY')
    api_secret = os.environ.get('JODO_API_SECRET')
    auth_string = base64.b64encode(f'{api_key}:{api_secret}'.encode()).decode()

    payload = {
        'name': parent_name,
        'phone': parent_phone,
        'email': parent_email,
        'student_name': student_name,
        'identifier': admission_number,
        'details': [
            {'component_type': city.jodo_component_code, 'amount': round(total, 2)}
        ]
    }
    if city.jodo_branch_code:
        payload['collector_code'] = city.jodo_branch_code


    try:
        response = requests.post(
            f'{base_url}/api/v1/integrations/pay/payment_links',
            headers={'Authorization': f'Basic {auth_string}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=15
        )
        data = response.json()

        if response.status_code in (200, 201) and data.get('status') == 'success':
            pending.jodo_order_id = data['data']['order_id']
            db.session.commit()

            session['cart'] = {}
            session['tracking_pending_id'] = pending.id

            return render_template('parent/redirect_to_jodo.html', jodo_url=data['data']['redirect_url'])
        else:
            print(f"JODO NON-SUCCESS RESPONSE: status_code={response.status_code}, body={response.text}")
            flash(f'Could not start payment — please try again (debug: {response.status_code} - {response.text})')
            return redirect(url_for('parent.bundle_view') if session.get('checkout_source') == 'bundle' else url_for('parent.view_cart'))

    except Exception as e:
        print(f"JODO API ERROR: {e}")
        flash(f'Could not connect to the payment gateway — please try again')
        return redirect(url_for('parent.bundle_view') if session.get('checkout_source') == 'bundle' else url_for('parent.view_cart'))

@parent.route('/payment-status')
def payment_status():
    pending_id = session.get('tracking_pending_id')
    if not pending_id:
        flash('No payment being tracked — please start again')
        return redirect(url_for('parent.select_city'))

    pending = PendingJodoOrder.query.get(pending_id)
    if not pending:
        flash('Order not found')
        return redirect(url_for('parent.select_city'))

    if pending.status == 'completed':
        order = Order.query.get(pending.resulting_order_id)
        session.pop('tracking_pending_id', None)
        return render_template('parent/order_success.html', order=order)

    return render_template('parent/payment_status.html', pending=pending)

@parent.route('/free-shop')
def free_shop():
    city_id = session.get('shop_city_id')
    student_class = session.get('shop_class')
    if not city_id or not student_class:
        return redirect(url_for('parent.select_city'))

    city = City.query.get_or_404(city_id)
    if not city.free_shopping_enabled:
        flash('This option is currently unavailable — please choose another option.')
        return redirect(url_for('parent.purchase_choice'))

    products = Product.query.filter(
        Product.city_id == city_id,
        Product.is_active == True,
        Product.stock_quantity > 0,
        db.or_(
            Product.applicable_class == student_class,
            Product.applicable_class.is_(None),
            Product.applicable_class.in_(['notebook', 'extra', 'stationary'])
        )
    ).order_by(Product.product_type, Product.name).all()

    cart = session.get('cart', {})
    return render_template('parent/free_shop.html', city=city, student_class=student_class, products=products, cart=cart)


@parent.route('/free-shop', methods=['POST'])
def free_shop_update():
    city_id = session.get('shop_city_id')
    if not city_id:
        return redirect(url_for('parent.select_city'))

    selected_ids = set(int(i) for i in request.form.getlist('product_id'))
    cart = {}
    for pid in selected_ids:
        qty = request.form.get(f'qty_{pid}', '1').strip()
        try:
            qty = int(qty)
        except ValueError:
            qty = 1
        if qty > 0:
            cart[str(pid)] = qty

    session['cart'] = cart
    session['checkout_source'] = 'free_shop'
    flash('Cart updated')
    return redirect(url_for('parent.view_cart'))





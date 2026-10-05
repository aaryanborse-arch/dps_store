import random
import string
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from app import db
from app.models import CouponOrder
from app.parent import normalize_admission_text

JODO_LINK = "https://pay.jodo.in/your-school-payment-link"  # replace with your real Jodo payment link

coupons = Blueprint('coupons', __name__, url_prefix='/shop/coupon')

MONTHLY_LIMIT = 500
AMOUNT_OPTIONS = [100, 150, 200, 250, 300, 350, 400, 450, 500]


def generate_coupon_otp():
    return ''.join(random.choices(string.digits, k=6))


def used_this_month(city_id, admission_number):
    now = datetime.utcnow()
    normalized = normalize_admission_text(admission_number)

    records = CouponOrder.query.filter(
        CouponOrder.city_id == city_id
    ).all()

    total = 0.0
    for r in records:
        if normalize_admission_text(r.admission_number) == normalized and \
           r.created_at.year == now.year and r.created_at.month == now.month:
            total += r.amount
    return total


@coupons.route('/')
def coupon_view():
    city_id = session.get('shop_city_id')
    admission_number = session.get('shop_admission_number')
    if not city_id or not admission_number:
        return redirect(url_for('parent.select_city'))

    used = used_this_month(city_id, admission_number)
    remaining = max(0, MONTHLY_LIMIT - used)
    valid_options = [a for a in AMOUNT_OPTIONS if a <= remaining]

    return render_template('parent/coupon.html', used=used, remaining=remaining,
                            monthly_limit=MONTHLY_LIMIT, valid_options=valid_options)


@coupons.route('/checkout', methods=['POST'])
def coupon_checkout():
    city_id = session.get('shop_city_id')
    admission_number = session.get('shop_admission_number')

    if not city_id or not admission_number:
        return redirect(url_for('parent.select_city'))

    try:
        amount = round(float(request.form.get('amount', '0')))
    except ValueError:
        amount = 0

    if amount <= 0:
        flash('Please select a valid coupon amount')
        return redirect(url_for('coupons.coupon_view'))

    used = used_this_month(city_id, admission_number)
    if used + amount > MONTHLY_LIMIT:
        remaining = max(0, MONTHLY_LIMIT - used)
        flash(f'This month\'s ₹{MONTHLY_LIMIT} canteen coupon limit has been reached. You have already used ₹{used:.0f} — only ₹{remaining:.0f} remaining this month.')
        return redirect(url_for('coupons.coupon_view'))

    # hold the requested amount in session — nothing is created in the database yet
    session['pending_coupon_amount'] = amount

    return render_template('parent/coupon_payment.html', amount=amount, jodo_link=JODO_LINK)


@coupons.route('/confirm-payment', methods=['POST'])
def coupon_confirm_payment():
    city_id = session.get('shop_city_id')
    admission_number = session.get('shop_admission_number')
    student_name = session.get('shop_student_name')
    student_class = session.get('shop_class')
    amount = session.get('pending_coupon_amount')

    if not city_id or not admission_number or not amount:
        flash('Your session expired — please start again')
        return redirect(url_for('coupons.coupon_view'))

    # re-check quota at confirm time too, in case they opened two tabs or waited a long time
    used = used_this_month(city_id, admission_number)
    if used + amount > MONTHLY_LIMIT:
        remaining = max(0, MONTHLY_LIMIT - used)
        flash(f'This month\'s ₹{MONTHLY_LIMIT} canteen coupon limit has been reached. Only ₹{remaining:.0f} remaining.')
        session.pop('pending_coupon_amount', None)
        return redirect(url_for('coupons.coupon_view'))

    otp = generate_coupon_otp()
    new_coupon = CouponOrder(
        city_id=city_id,
        admission_number=admission_number,
        student_name=student_name,
        student_class=student_class,
        amount=amount,
        otp_code=otp,
        status='pending'
    )
    db.session.add(new_coupon)
    db.session.commit()
    session.pop('pending_coupon_amount', None)

    return render_template('parent/coupon_success.html', coupon=new_coupon)
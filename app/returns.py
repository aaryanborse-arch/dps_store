import random
import string
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from app import db
from app.models import Bill, BillItem, ReturnRecord, ReturnRecordItem, Product, City
from app.inventory import store_staff_required
from app.city_utils import get_active_city_id
from app.activity_log import log_activity
from sqlalchemy import text
from datetime import timedelta

returns_bp = Blueprint('returns_bp', __name__, url_prefix='/returns')


def generate_credit_note_number(city):
    result = db.session.execute(
        text('UPDATE cities SET next_credit_note_number = COALESCE(next_credit_note_number, 1) + 1 WHERE id = :city_id RETURNING COALESCE(next_credit_note_number, 1) - 1'),
        {'city_id': city.id}
    )
    number = result.scalar()
    db.session.commit()
    return f'CN-{number:05d}'   


@returns_bp.route('/', methods=['GET'])
@login_required
@store_staff_required
def find_bill():
    bill_number = request.args.get('bill_number', '').strip()
    bill = None
    already_returned = {}

    if bill_number:
        city_id = get_active_city_id()
        bill = Bill.query.filter_by(bill_number=bill_number, city_id=city_id).first()
        if not bill:
            flash('No bill found with that invoice number for your active school')
        else:
            for item in bill.items:
                returned_qty = db.session.query(db.func.coalesce(db.func.sum(ReturnRecordItem.quantity_returned), 0)) \
                    .filter(ReturnRecordItem.bill_item_id == item.id).scalar()
                already_returned[item.id] = returned_qty

    city_id = get_active_city_id()

    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    history_query = ReturnRecord.query.filter_by(city_id=city_id)
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        history_query = history_query.filter(ReturnRecord.created_at >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        history_query = history_query.filter(ReturnRecord.created_at < end_date)

    history = history_query.order_by(ReturnRecord.created_at.desc()).limit(200).all()

    return render_template('returns/find_bill.html', bill=bill, already_returned=already_returned,
                            history=history, start_date=start_date_str, end_date=end_date_str)


@returns_bp.route('/submit', methods=['POST'])
@login_required
@store_staff_required
def submit_return():
    city_id = get_active_city_id()
    bill_id = request.form.get('bill_id')
    reason = request.form.get('reason', '').strip() or None

    bill = Bill.query.get_or_404(int(bill_id))
    if bill.city_id != city_id:
        flash('Access denied')
        return redirect(url_for('returns_bp.find_bill'))

    return_items = []
    for item in bill.items:
        qty_str = request.form.get(f'return_qty_{item.id}', '0').strip()
        try:
            qty = int(qty_str)
        except ValueError:
            qty = 0
        if qty <= 0:
            continue

        already_returned = db.session.query(db.func.coalesce(db.func.sum(ReturnRecordItem.quantity_returned), 0)) \
            .filter(ReturnRecordItem.bill_item_id == item.id).scalar()
        remaining = item.quantity - already_returned
        if qty > remaining:
            flash(f'Cannot return {qty} of "{item.product_name}" — only {remaining} available to return')
            return redirect(url_for('returns_bp.find_bill', bill_number=bill.bill_number))

        return_items.append((item, qty))

    if not return_items:
        flash('Select at least one item with a quantity to return')
        return redirect(url_for('returns_bp.find_bill', bill_number=bill.bill_number))

    from app.models import City
    active_city = City.query.get(city_id)

    new_return = ReturnRecord(
        credit_note_number=generate_credit_note_number(active_city),
        bill_id=bill.id,
        city_id=city_id,
        recorded_by_id=current_user.id,
        reason=reason
    )
    db.session.add(new_return)
    db.session.flush()

    for item, qty in return_items:
        unit_price = item.price
        taxable_amount = round(unit_price * qty, 2)
        gst_amount = 0.0 if item.is_gst_exempt else round(taxable_amount * item.gst_percent / 100, 2)
        total_amount = round(taxable_amount + gst_amount)

        db.session.add(ReturnRecordItem(
            return_record_id=new_return.id,
            bill_item_id=item.id,
            product_id=item.product_id,
            product_name=item.product_name,
            hsn_number=item.hsn_number,
            quantity_returned=qty,
            price=unit_price,
            gst_percent=item.gst_percent,
            is_gst_exempt=item.is_gst_exempt,
            taxable_amount=taxable_amount,
            gst_amount=gst_amount,
            total_amount=total_amount
        ))

        if item.product_id:
            product = Product.query.get(item.product_id)
            if product:
                product.stock_quantity += qty

    db.session.commit()

    log_activity('Recorded return', f'Credit Note {new_return.credit_note_number} for Bill {bill.bill_number} ({bill.student_name})')
    flash(f'Return recorded — Credit Note {new_return.credit_note_number}')
    return redirect(url_for('returns_bp.view_credit_note', return_id=new_return.id))


@returns_bp.route('/<int:return_id>')
@login_required
def view_credit_note(return_id):
    return_record = ReturnRecord.query.get_or_404(return_id)
    if current_user.role == 'store_staff' and return_record.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('returns_bp.find_bill'))
    return render_template('returns/credit_note.html', r=return_record)


@returns_bp.route('/<int:return_id>/download')
@login_required
def download_credit_note(return_id):
    from app.pdf_utils import generate_credit_note_pdf
    return_record = ReturnRecord.query.get_or_404(return_id)
    if current_user.role == 'store_staff' and return_record.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('returns_bp.find_bill'))

    pdf_buffer = generate_credit_note_pdf(return_record)
    return send_file(pdf_buffer, as_attachment=False,
                      download_name=f'{return_record.credit_note_number}.pdf', mimetype='application/pdf')


@returns_bp.route('/admin')
@login_required
def admin_view_returns():
    if current_user.role != 'super_admin':
        flash('Access denied')
        return redirect(url_for('auth.dashboard'))

    city_id_param = request.args.get('city_id', 'all')
    city_id = None if city_id_param == 'all' else int(city_id_param)

    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    query = ReturnRecord.query
    if city_id is not None:
        query = query.filter_by(city_id=city_id)
    if start_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        query = query.filter(ReturnRecord.created_at >= start_date)
    if end_date_str:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(ReturnRecord.created_at < end_date)

    records = query.order_by(ReturnRecord.created_at.desc()).all()

    all_cities = City.query.order_by(City.name).all()
    return render_template('returns/admin_view.html', records=records, all_cities=all_cities,
                            selected_city_id=city_id_param, start_date=start_date_str, end_date=end_date_str)
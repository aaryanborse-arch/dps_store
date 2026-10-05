from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from app.models import Supplier, PurchaseRecord, PurchaseRecordItem, City
from app.city_utils import get_active_city_id
from app import db


vendors = Blueprint('vendors', __name__, url_prefix='/vendors')


def get_scope():
    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        return city_id, city_id_param
    elif current_user.role == 'store_staff':
        return get_active_city_id(), 'all'
    return None, 'all'


@vendors.route('/')
@login_required
def vendor_list():
    if current_user.role not in ('super_admin', 'store_staff'):
        flash('Access denied')
        return redirect(url_for('auth.dashboard'))

    city_id, selected_city_id = get_scope()

    query = PurchaseRecord.query
    if city_id is not None:
        query = query.filter_by(city_id=city_id)
    records = query.all()

    supplier_data = {}
    for r in records:
        sid = r.supplier_id
        if sid not in supplier_data:
            supplier_data[sid] = {'supplier': r.supplier, 'total_amount': 0.0, 'total_gst': 0.0, 'invoice_count': 0}
        supplier_data[sid]['total_amount'] += r.total_amount()
        supplier_data[sid]['total_gst'] += r.total_gst()
        supplier_data[sid]['invoice_count'] += 1

    suppliers_summary = sorted(supplier_data.values(), key=lambda x: x['supplier'].name)
    all_cities = City.query.order_by(City.name).all() if current_user.role == 'super_admin' else None

    return render_template('vendors/list.html', suppliers_summary=suppliers_summary,
                            all_cities=all_cities, selected_city_id=selected_city_id)


@vendors.route('/<int:supplier_id>')
@login_required
def vendor_detail(supplier_id):
    if current_user.role not in ('super_admin', 'store_staff'):
        flash('Access denied')
        return redirect(url_for('auth.dashboard'))

    supplier = Supplier.query.get_or_404(supplier_id)
    city_id, _ = get_scope()

    query = PurchaseRecord.query.filter_by(supplier_id=supplier_id)
    if city_id is not None:
        query = query.filter_by(city_id=city_id)
    records = query.order_by(PurchaseRecord.created_at.desc()).all()

    return render_template('vendors/detail.html', supplier=supplier, records=records)

@vendors.route('/<int:supplier_id>/delete', methods=['POST'])
@login_required
def delete_vendor(supplier_id):
    if current_user.role not in ('super_admin', 'store_staff'):
        flash('Access denied')
        return redirect(url_for('auth.dashboard'))

    supplier = Supplier.query.get_or_404(supplier_id)
    supplier_name = supplier.name

    records = PurchaseRecord.query.filter_by(supplier_id=supplier_id).all()
    for record in records:
        PurchaseRecordItem.query.filter_by(purchase_record_id=record.id).delete()
        db.session.delete(record)

    db.session.delete(supplier)
    db.session.commit()
    flash(f'Vendor "{supplier_name}" and its purchase records removed')
    return redirect(url_for('vendors.vendor_list'))
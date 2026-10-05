from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from app import db
from app.models import PurchaseInvoiceUpload, City
from app.inventory import store_staff_required
from app.city_utils import get_active_city_id
from app.activity_log import log_activity

purchase_invoices = Blueprint('purchase_invoices', __name__, url_prefix='/purchase-invoices')

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@purchase_invoices.route('/', methods=['GET', 'POST'])
@login_required
@store_staff_required
def manage_invoices():
    city_id = get_active_city_id()

    if request.method == 'POST':
        vendor_name = request.form.get('vendor_name', '').strip()
        invoice_date_str = request.form.get('invoice_date', '').strip()
        notes = request.form.get('notes', '').strip() or None
        file = request.files.get('invoice_file')

        if not vendor_name or not invoice_date_str or not file or file.filename == '':
            flash('Vendor name, invoice date, and a file are all required')
            return redirect(url_for('purchase_invoices.manage_invoices'))

        if not allowed_file(file.filename):
            flash('Only PDF, PNG, or JPG files are allowed')
            return redirect(url_for('purchase_invoices.manage_invoices'))

        try:
            invoice_date = datetime.strptime(invoice_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date')
            return redirect(url_for('purchase_invoices.manage_invoices'))

        file_bytes = file.read()
        if len(file_bytes) > 4 * 1024 * 1024:
            flash('File too large — please keep it under 4MB (large scans/photos often exceed this; try compressing the image or scanning at a lower resolution)')
            return redirect(url_for('purchase_invoices.manage_invoices'))

        upload = PurchaseInvoiceUpload(
            city_id=city_id,
            uploaded_by_id=current_user.id,
            vendor_name=vendor_name,
            invoice_date=invoice_date,
            notes=notes,
            file_name=file.filename,
            file_mimetype=file.mimetype,
            file_data=file_bytes
        )
        db.session.add(upload)
        db.session.commit()

        log_activity('Uploaded purchase invoice', f'Vendor: {vendor_name}, Date: {invoice_date}')
        flash(f'Invoice from "{vendor_name}" uploaded successfully')
        return redirect(url_for('purchase_invoices.manage_invoices'))

    invoices = PurchaseInvoiceUpload.query.filter_by(city_id=city_id).order_by(PurchaseInvoiceUpload.uploaded_at.desc()).all()
    return render_template('purchase_invoices/manage.html', invoices=invoices)


@purchase_invoices.route('/<int:invoice_id>/download')
@login_required
def download_invoice(invoice_id):
    invoice = PurchaseInvoiceUpload.query.get_or_404(invoice_id)

    if current_user.role == 'store_staff' and invoice.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('purchase_invoices.manage_invoices'))

    return send_file(BytesIO(invoice.file_data), download_name=invoice.file_name,
                      mimetype=invoice.file_mimetype, as_attachment=False)


@purchase_invoices.route('/admin')
@login_required
def admin_view_invoices():
    if current_user.role != 'super_admin':
        flash('Access denied')
        return redirect(url_for('auth.dashboard'))

    city_id_param = request.args.get('city_id', 'all')
    city_id = None if city_id_param == 'all' else int(city_id_param)

    query = PurchaseInvoiceUpload.query
    if city_id is not None:
        query = query.filter_by(city_id=city_id)
    invoices = query.order_by(PurchaseInvoiceUpload.uploaded_at.desc()).all()

    all_cities = City.query.order_by(City.name).all()
    return render_template('purchase_invoices/admin_view.html', invoices=invoices, all_cities=all_cities, selected_city_id=city_id_param)
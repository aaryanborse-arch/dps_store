from datetime import datetime, date
from calendar import monthrange
from flask import Blueprint, render_template, request, send_file
from flask_login import login_required, current_user
from app import db
from app.models import Bill, BillItem, City, Product, StockLog
from app.city_utils import get_active_city_id
from app.pdf_utils import generate_report_pdf, generate_day_wise_pdf, generate_gst_report_pdf
from app.excel_utils import generate_day_wise_excel, generate_report_excel, generate_gst_report_excel
from app.inventory import section_label, class_value_to_key
from app.class_options import CLASS_OPTIONS

reports = Blueprint('reports', __name__, url_prefix='/reports')


def get_date_range(period, ref_date):
    if period == 'daily':
        start = datetime(ref_date.year, ref_date.month, ref_date.day, 0, 0, 0)
        end = datetime(ref_date.year, ref_date.month, ref_date.day, 23, 59, 59)
    elif period == 'monthly':
        last_day = monthrange(ref_date.year, ref_date.month)[1]
        start = datetime(ref_date.year, ref_date.month, 1, 0, 0, 0)
        end = datetime(ref_date.year, ref_date.month, last_day, 23, 59, 59)
    elif period == 'yearly':
        start = datetime(ref_date.year, 1, 1, 0, 0, 0)
        end = datetime(ref_date.year, 12, 31, 23, 59, 59)
    else:
        start = datetime(ref_date.year, ref_date.month, ref_date.day, 0, 0, 0)
        end = datetime(ref_date.year, ref_date.month, ref_date.day, 23, 59, 59)
    return start, end


def get_custom_range(start_date, end_date):
    if end_date < start_date:
        start_date, end_date = end_date, start_date
    start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
    return start, end


def build_report_data(city_id, period, ref_date, stock_class_filter=None):
    start, end = get_date_range(period, ref_date)

    bill_query = Bill.query.filter(Bill.created_at >= start, Bill.created_at <= end)
    if city_id is not None:
        bill_query = bill_query.filter(Bill.city_id == city_id)
    total_bills = bill_query.count()
    total_amount = sum(b.total_amount for b in bill_query.all())

    product_query = Product.query
    if city_id is not None:
        product_query = product_query.filter(Product.city_id == city_id)
    candidate_products = product_query.order_by(Product.name).all()

    # only include a product if it was active at some point during (or before) this report's period —
    # i.e. it wasn't deactivated before the period even started
    all_products = [
        p for p in candidate_products
        if p.is_active or p.deactivated_at is None or p.deactivated_at >= start
    ]
    product_ids = [p.id for p in all_products]

    stock_overview = []

    if product_ids:
        logs = StockLog.query.filter(StockLog.product_id.in_(product_ids), StockLog.created_at <= end).all()

        inward_before = {}
        inward_within = {}
        for log in logs:
            bucket = inward_before if log.created_at < start else inward_within
            bucket[log.product_id] = bucket.get(log.product_id, 0) + log.quantity_added

        sold_rows = db.session.query(BillItem.product_id, BillItem.quantity, Bill.created_at).join(
            Bill, BillItem.bill_id == Bill.id
        ).filter(BillItem.product_id.in_(product_ids), Bill.created_at <= end)
        if city_id is not None:
            sold_rows = sold_rows.filter(Bill.city_id == city_id)

        sold_before = {}
        sold_within = {}
        for pid, qty, bill_created_at in sold_rows.all():
            bucket = sold_before if bill_created_at < start else sold_within
            bucket[pid] = bucket.get(pid, 0) + qty

        
        for p in all_products:
            opening = inward_before.get(p.id, 0) - sold_before.get(p.id, 0)
            inward_stock = inward_within.get(p.id, 0)
            sales = sold_within.get(p.id, 0)
            closing = opening + inward_stock - sales

            class_key = class_value_to_key(p.applicable_class)
            if class_key == 'extra':
                class_key = 'stationary'

            stock_overview.append({
                'name': p.name,
                'year': p.year,
                'price': p.price,
                'opening_stock': opening,
                'current_stock': p.stock_quantity,
                'sales': sales,
                'inward_stock': inward_stock,
                'closing_stock': closing,
                'class_key': class_key,
                'class_label': section_label(class_key)
            })
    grouped_stock = {}
    order = []
    for s in stock_overview:
        if s['class_key'] not in grouped_stock:
            grouped_stock[s['class_key']] = {'label': s['class_label'], 'products': []}
            order.append(s['class_key'])
        grouped_stock[s['class_key']]['products'].append(s)
    def sort_key(k):
        return (0, int(k)) if k.isdigit() else (1, k)
    order.sort(key=sort_key)

    grouped_stock_overview = [grouped_stock[k] for k in order]

    if stock_class_filter:
        stock_overview_filtered = [s for s in stock_overview if s['class_key'] == stock_class_filter]
    else:
        stock_overview_filtered = stock_overview

    return {
        'start': start, 'end': end,
        'total_amount': total_amount, 'total_bills': total_bills,
        'stock_overview': stock_overview_filtered,
        'grouped_stock_overview': grouped_stock_overview
    }
    


@reports.route('/')
@login_required
def view_reports():
    period = request.args.get('period', 'daily')
    date_str = request.args.get('date')
    ref_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    stock_class_filter = request.args.get('stock_class') or None

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        all_cities = City.query.order_by(City.name).all()
    elif current_user.role == 'store_staff':
        city_id = get_active_city_id()
        all_cities = None
    else:
        city_id = None
        all_cities = None

    data = build_report_data(city_id, period, ref_date, stock_class_filter)

    return render_template(
        'reports/view.html',
        period=period, ref_date=ref_date, data=data,
        all_cities=all_cities, selected_city_id=request.args.get('city_id', 'all'),
        stock_class_filter=stock_class_filter, class_options=CLASS_OPTIONS
    )


@reports.route('/download')
@login_required
def download_report():
    period = request.args.get('period', 'daily')
    date_str = request.args.get('date')
    ref_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    else:
        city_id = get_active_city_id()
        city_label = City.query.get(city_id).name if city_id else 'Unknown'

    stock_class_filter = request.args.get('stock_class') or None
    data = build_report_data(city_id, period, ref_date, stock_class_filter)
    pdf_buffer = generate_report_pdf(period, ref_date, data, city_label)

    filename = f'{period}_report_{ref_date.strftime("%Y%m%d")}.pdf'
    return send_file(pdf_buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports.route('/download-excel')
@login_required
def download_report_excel():
    period = request.args.get('period', 'daily')
    date_str = request.args.get('date')
    ref_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    else:
        city_id = get_active_city_id()
        city_label = City.query.get(city_id).name if city_id else 'Unknown'

    stock_class_filter = request.args.get('stock_class') or None
    data = build_report_data(city_id, period, ref_date, stock_class_filter)
    excel_buffer = generate_report_excel(period, ref_date, data, city_label)

    filename = f'{period}_stock_report_{ref_date.strftime("%Y%m%d")}.xlsx'
    return send_file(excel_buffer, as_attachment=True, download_name=filename,
                      mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def build_gst_report_data(city_id, start, end):
    query = Bill.query.filter(Bill.created_at >= start, Bill.created_at <= end)
    if city_id is not None:
        query = query.filter(Bill.city_id == city_id)
    bills = query.order_by(Bill.created_at).all()

    bill_rows = []
    total_taxable = 0.0
    total_cgst = 0.0
    total_sgst = 0.0

    for b in bills:
        bill_taxable = 0.0
        bill_gst = 0.0
        for item in b.items:
            taxable = item.subtotal
            gst_amount = 0.0 if item.is_gst_exempt else round(taxable * item.gst_percent / 100, 2)
            bill_taxable += taxable
            bill_gst += gst_amount

        bill_cgst = round(bill_gst / 2, 2)
        bill_sgst = round(bill_gst / 2, 2)

        bill_rows.append({
            'bill_number': b.bill_number,
            'date': b.created_at,
            'city': b.city.name,
            'taxable': round(bill_taxable, 2),
            'cgst': bill_cgst,
            'sgst': bill_sgst,
            'total_gst': round(bill_gst, 2),
            'grand_total': round(bill_taxable + bill_gst, 2)
        })

        total_taxable += bill_taxable
        total_cgst += bill_cgst
        total_sgst += bill_sgst

    return {
        'start': start, 'end': end, 'bill_rows': bill_rows,
        'total_taxable': round(total_taxable, 2),
        'total_cgst': round(total_cgst, 2),
        'total_sgst': round(total_sgst, 2),
        'total_gst': round(total_cgst + total_sgst, 2),
        'grand_total': round(total_taxable + total_cgst + total_sgst, 2)
    }


def resolve_range_from_request(default_period='daily'):
    """Custom range (start_date/end_date) takes priority; otherwise falls back to period+date."""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if start_date_str and end_date_str:
        try:
            sd = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            ed = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            start, end = get_custom_range(sd, ed)
            return start, end, 'custom', sd, ed
        except ValueError:
            pass

    period = request.args.get('period', default_period)
    date_str = request.args.get('date')
    ref_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    start, end = get_date_range(period, ref_date)
    return start, end, period, ref_date, ref_date


@reports.route('/gst')
@login_required
def gst_report():
    start, end, period, start_date, end_date = resolve_range_from_request()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        all_cities = City.query.order_by(City.name).all()
    elif current_user.role == 'store_staff':
        city_id = get_active_city_id()
        all_cities = None
    else:
        city_id = None
        all_cities = None

    data = build_gst_report_data(city_id, start, end)

    return render_template(
        'reports/gst_view.html',
        period=period, start_date=start_date, end_date=end_date, data=data,
        all_cities=all_cities, selected_city_id=request.args.get('city_id', 'all')
    )


@reports.route('/gst/download')
@login_required
def download_gst_report():
    start, end, period, start_date, end_date = resolve_range_from_request()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    else:
        city_id = get_active_city_id()
        city_label = City.query.get(city_id).name if city_id else 'Unknown'

    data = build_gst_report_data(city_id, start, end)
    pdf_buffer = generate_gst_report_pdf(period, start_date, data, city_label)

    filename = f'gst_report_{start_date.strftime("%Y%m%d")}_to_{end_date.strftime("%Y%m%d")}.pdf'
    return send_file(pdf_buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports.route('/gst/download-excel')
@login_required
def download_gst_report_excel():
    start, end, period, start_date, end_date = resolve_range_from_request()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    else:
        city_id = get_active_city_id()
        city_label = City.query.get(city_id).name if city_id else 'Unknown'

    data = build_gst_report_data(city_id, start, end)
    excel_buffer = generate_gst_report_excel(period, start_date, data, city_label)

    filename = f'gst_report_{start_date.strftime("%Y%m%d")}_to_{end_date.strftime("%Y%m%d")}.xlsx'
    return send_file(excel_buffer, as_attachment=True, download_name=filename,
                      mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def build_day_wise_report(city_id, start, end):
    query = Bill.query.filter(Bill.created_at >= start, Bill.created_at <= end)
    if city_id is not None:
        query = query.filter(Bill.city_id == city_id)
    bills = query.order_by(Bill.created_at).all()

    STANDARD_RATES = [5.0, 18.0]
    rate_set = set(STANDARD_RATES)
    for b in bills:
        for item in b.items:
            if not item.is_gst_exempt:
                rate_set.add(item.gst_percent)
    rates = sorted(rate_set)

    rows = []
    total_exempt = 0.0
    total_taxable_by_rate = {r: 0.0 for r in rates}
    total_gst_by_rate = {r: 0.0 for r in rates}
    total_grand = 0.0

    for idx, b in enumerate(bills, start=1):
        exempt_amt = 0.0
        taxable_by_rate = {r: 0.0 for r in rates}
        gst_by_rate = {r: 0.0 for r in rates}

        for item in b.items:
            if item.is_gst_exempt:
                exempt_amt += item.subtotal
            else:
                taxable_by_rate[item.gst_percent] = taxable_by_rate.get(item.gst_percent, 0) + item.subtotal
                gst_by_rate[item.gst_percent] = gst_by_rate.get(item.gst_percent, 0) + round(item.subtotal * item.gst_percent / 100, 2)

        grand_total = exempt_amt + sum(taxable_by_rate.values()) + sum(gst_by_rate.values())

        rows.append({
            'sr_no': idx,
            'bill_number': b.bill_number,
            'date': b.created_at,
            'student_name': b.student_name or '-',
            'student_class': b.student_class or '-',
            'payment_mode': b.payment_method or '-',
            'exempt_amt': round(exempt_amt, 2),
            'taxable_by_rate': {r: round(v, 2) for r, v in taxable_by_rate.items()},
            'gst_by_rate': {r: round(v, 2) for r, v in gst_by_rate.items()},
            'grand_total': round(grand_total, 2)
        })

        total_exempt += exempt_amt
        for r in rates:
            total_taxable_by_rate[r] += taxable_by_rate[r]
            total_gst_by_rate[r] += gst_by_rate[r]
        total_grand += grand_total

    return {
        'start': start, 'end': end, 'rows': rows, 'rates': rates,
        'total_exempt': round(total_exempt, 2),
        'total_taxable_by_rate': {r: round(v, 2) for r, v in total_taxable_by_rate.items()},
        'total_gst_by_rate': {r: round(v, 2) for r, v in total_gst_by_rate.items()},
        'total_grand': round(total_grand, 2)
    }


@reports.route('/day-wise')
@login_required
def day_wise_report():
    start, end, period, start_date, end_date = resolve_range_from_request()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        all_cities = City.query.order_by(City.name).all()
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    elif current_user.role == 'store_staff':
        city_id = get_active_city_id()
        all_cities = None
        city_label = City.query.get(city_id).name if city_id else 'Unknown'
    else:
        city_id = None
        all_cities = None
        city_label = 'Unknown'

    data = build_day_wise_report(city_id, start, end)

    return render_template('reports/day_wise.html', data=data, all_cities=all_cities,
                            selected_city_id=request.args.get('city_id', 'all'), city_label=city_label,
                            start_date=start_date, end_date=end_date)


@reports.route('/day-wise/download')
@login_required
def download_day_wise_report():
    start, end, period, start_date, end_date = resolve_range_from_request()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    else:
        city_id = get_active_city_id()
        city_label = City.query.get(city_id).name if city_id else 'Unknown'

    data = build_day_wise_report(city_id, start, end)
    pdf_buffer = generate_day_wise_pdf(data, city_label)

    filename = f'sales_report_{start_date.strftime("%Y%m%d")}_to_{end_date.strftime("%Y%m%d")}.pdf'
    return send_file(pdf_buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


@reports.route('/day-wise/download-excel')
@login_required
def download_day_wise_excel():
    start, end, period, start_date, end_date = resolve_range_from_request()

    if current_user.role == 'super_admin':
        city_id_param = request.args.get('city_id', 'all')
        city_id = None if city_id_param == 'all' else int(city_id_param)
        city_label = 'All Schools' if city_id is None else City.query.get(city_id).name
    else:
        city_id = get_active_city_id()
        city_label = City.query.get(city_id).name if city_id else 'Unknown'

    data = build_day_wise_report(city_id, start, end)
    excel_buffer = generate_day_wise_excel(data, city_label)

    filename = f'sales_report_{start_date.strftime("%Y%m%d")}_to_{end_date.strftime("%Y%m%d")}.xlsx'
    return send_file(excel_buffer, as_attachment=True, download_name=filename,
                      mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
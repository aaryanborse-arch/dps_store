from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ---- EDIT THESE with your actual store details ----
STORE_NAME = "HIMGIRI GOODS PVT. LTD."
STORE_ADDRESS = "35, Wadi, Nagpur - 440023"
STORE_EXTRA_LINE = "Extra Counter at - Delhi Public School Nagpur"
STORE_GSTIN = "27AABCH8268F1ZE"
# ----------------------------------------------------

_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
         'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
         'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _two_digit_words(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (' ' + _ONES[n % 10] if n % 10 else '')).strip()


def _three_digit_words(n):
    if n >= 100:
        return _ONES[n // 100] + ' Hundred' + (' ' + _two_digit_words(n % 100) if n % 100 else '')
    return _two_digit_words(n)


def number_to_words_indian(num):
    if num == 0:
        return 'Zero'
    crore, num = divmod(num, 10000000)
    lakh, num = divmod(num, 100000)
    thousand, hundred = divmod(num, 1000)

    parts = []
    if crore:
        parts.append(_three_digit_words(crore) + ' Crore')
    if lakh:
        parts.append(_two_digit_words(lakh) + ' Lakh')
    if thousand:
        parts.append(_two_digit_words(thousand) + ' Thousand')
    if hundred:
        parts.append(_three_digit_words(hundred))
    return ' '.join(parts).strip()


def amount_to_words(amount):
    rupees = int(amount)
    paise = round((amount - rupees) * 100)
    words = f"Rupees {number_to_words_indian(rupees)} Only"
    if paise:
        words = f"Rupees {number_to_words_indian(rupees)} and {number_to_words_indian(paise)} Paise Only"
    return words


def to_roman(num_str):
    try:
        num = int(num_str)
    except (TypeError, ValueError):
        from app.class_options import CLASS_LABELS
        return CLASS_LABELS.get(num_str, num_str)
    vals = [
        (1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
        (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
        (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')
    ]
    result = ''
    for v, sym in vals:
        while num >= v:
            result += sym
            num -= v
    return result or num_str


def build_invoice_elements(bill, copy_label=None):
    styles = getSampleStyleSheet()

    company_style = ParagraphStyle('Company', parent=styles['Heading2'], fontSize=13, spaceAfter=2)
    addr_style = ParagraphStyle('Addr', parent=styles['Normal'], fontSize=8.5, spaceAfter=1)
    invoice_title_style = ParagraphStyle('InvTitle', parent=styles['Heading2'], fontSize=14, alignment=2)
    meta_right_style = ParagraphStyle('MetaRight', parent=styles['Normal'], fontSize=9, alignment=2)
    copy_label_style = ParagraphStyle('CopyLabel', parent=styles['Normal'], fontSize=9, alignment=2, textColor=colors.grey)
    cell_wrap_style = ParagraphStyle('CellWrap', parent=styles['Normal'], fontSize=7, leading=8.5)

    elements = []

    if copy_label:
        elements.append(Paragraph(f"<b>{copy_label}</b>", copy_label_style))
        elements.append(Spacer(1, 4))

    extra_line = bill.city.extra_counter_line if bill.city and bill.city.extra_counter_line else STORE_EXTRA_LINE
    active_gstin = bill.city.gstin_number if bill.city and bill.city.gstin_number else STORE_GSTIN
    left_cell = [
        Paragraph(STORE_NAME, company_style),
        Paragraph(STORE_ADDRESS, addr_style),
        Paragraph(extra_line, addr_style),
        Paragraph(f"GSTIN NO. {active_gstin}", addr_style),
    ]
    issued_by = bill.created_by.username if bill.created_by else '-'
    right_cell = [
        Paragraph('<u>TAX INVOICE</u>', invoice_title_style),
        Spacer(1, 4),
        Paragraph(f"Invoice No.: {bill.bill_number}", meta_right_style),
        Paragraph(f"Date: {bill.created_at.strftime('%d-%m-%Y')}", meta_right_style),
        Paragraph(f"Payment: {bill.payment_method or '-'}", meta_right_style),
        Paragraph(f"Issued By: {issued_by}", meta_right_style),
    ]

    header_table = Table([[left_cell, right_cell]], colWidths=[280, 220])
    header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    meta_data = [
        ['Student Name:', bill.student_name or '-', 'Class:', to_roman(bill.student_class) if bill.student_class else '-'],
    ]
    meta_table = Table(meta_data, colWidths=[80, 180, 60, 150])
    meta_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    TOTAL_WIDTH = [22, 130, 55, 65, 40, 25, 40, 38, 56]
    hsn_summary = {}
    total_qty = 0
    grand_taxable = 0.0
    grand_tax = 0.0
    grand_total_rounded = 0
    raw_items = []

    for item in bill.items:
        base_amount = item.subtotal
        gst_amount = 0.0 if item.is_gst_exempt else round(base_amount * item.gst_percent / 100, 2)
        item_amount_rounded = round(base_amount + gst_amount)

        product_ref = None
        if item.product_id:
            from app.models import Product
            product_ref = Product.query.get(item.product_id)
        is_elective = bool(product_ref and product_ref.is_elective)

        raw_items.append({
            'name': item.product_name, 'hsn': item.hsn_number, 'qty': item.quantity,
            'price': item.price, 'gst_percent': item.gst_percent, 'is_exempt': item.is_gst_exempt,
            'base_amount': base_amount, 'amount_rounded': item_amount_rounded,
            'subject': item.subject, 'is_elective': is_elective
        })

        total_qty += item.quantity
        grand_taxable += base_amount
        grand_tax += gst_amount
        grand_total_rounded += item_amount_rounded

        key = (item.gst_percent, item.is_gst_exempt)
        if key not in hsn_summary:
            hsn_summary[key] = {'taxable': 0.0, 'gst': 0.0, 'hsns': set()}
        hsn_summary[key]['taxable'] += base_amount
        hsn_summary[key]['gst'] += gst_amount
        hsn_summary[key]['hsns'].add(item.hsn_number)

    def build_rows(items_list):
        by_subject = {}
        order = []
        singles = []
        for it in items_list:
            if it['subject']:
                if it['subject'] not in by_subject:
                    by_subject[it['subject']] = []
                    order.append(it['subject'])
                by_subject[it['subject']].append(it)
            else:
                singles.append(it)

        rows = []
        for subject in order:
            group = by_subject[subject]
            if len(group) > 1:
                names = ', '.join(g['name'] for g in group)
                hsns = ', '.join(sorted(set(g['hsn'] for g in group if g['hsn'])))
                qty_sum = sum(g['qty'] for g in group)
                rate_sum = sum(g['base_amount'] for g in group)
                amount_sum = sum(g['amount_rounded'] for g in group)
                gst_percents = set(g['gst_percent'] for g in group)
                is_exempts = set(g['is_exempt'] for g in group)
                if len(gst_percents) == 1 and len(is_exempts) == 1:
                    gst_display = 'Exempt' if group[0]['is_exempt'] else f"{group[0]['gst_percent']}%"
                else:
                    gst_display = 'Mixed'
                rows.append(['', Paragraph(names, cell_wrap_style), '-', Paragraph(subject, cell_wrap_style), hsns or '-', str(qty_sum), f'{rate_sum:.2f}', gst_display, f'{amount_sum}'])
            else:
                g = group[0]
                gst_display = 'Exempt' if g['is_exempt'] else f"{g['gst_percent']}%"
                rows.append(['', Paragraph(g['name'], cell_wrap_style), '-', Paragraph(subject, cell_wrap_style), g['hsn'], str(g['qty']), f"{g['price']:.2f}", gst_display, f"{g['amount_rounded']}"])
        for g in singles:
            gst_display = 'Exempt' if g['is_exempt'] else f"{g['gst_percent']}%"
            rows.append(['', Paragraph(g['name'], cell_wrap_style), '-', '-', g['hsn'], str(g['qty']), f"{g['price']:.2f}", gst_display, f"{g['amount_rounded']}"])

        for i, row in enumerate(rows, start=1):
            row[0] = str(i)
        return rows

    compulsory_rows = build_rows([i for i in raw_items if not i['is_elective']])
    elective_rows = build_rows([i for i in raw_items if i['is_elective']])

    table_data = [['S.No', 'Particulars', 'Publisher', 'Subject', 'HSN', 'Qty', 'Rate', 'GST%', 'Amount']] + compulsory_rows
    table_data.append(['', '', '', '', 'TOTAL', str(total_qty), '', '', f'{grand_total_rounded}'])
    total_row_idx = len(table_data) - 1

    items_table = Table(table_data, colWidths=TOTAL_WIDTH)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('FONTNAME', (0, total_row_idx), (-1, total_row_idx), 'Helvetica-Bold'),
        ('LINEABOVE', (0, total_row_idx), (-1, total_row_idx), 0.75, colors.black),
    ]))
    elements.append(items_table)

    if elective_rows:
        elements.append(Spacer(1, 8))
        elective_header = ParagraphStyle('ElectiveHeader', parent=styles['Normal'], fontSize=10, spaceAfter=4)
        elements.append(Paragraph('<b>Optional Subject</b>', elective_header))
        elective_table_data = [['S.No', 'Particulars', 'Publisher', 'Subject', 'HSN', 'Qty', 'Rate', 'GST%', 'Amount']] + elective_rows
        elective_table = Table(elective_table_data, colWidths=TOTAL_WIDTH)
        elective_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8B4513')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
        ]))
        elements.append(elective_table)

    is_interstate = bill.is_interstate() if hasattr(bill, 'is_interstate') else False

    if is_interstate:
        summary_col_widths = [180, 100, 90, 101]
        summary_data = [['HSN / SAC', 'Taxable Value', 'IGST Rate', 'IGST Amount']]
        for (gst_percent, is_exempt), vals in hsn_summary.items():
            hsn_list = ', '.join(sorted(vals['hsns']))
            summary_data.append([hsn_list, f"{vals['taxable']:.2f}", 'Exempt' if is_exempt else f'{gst_percent}%', f"{vals['gst']:.2f}"])
        hsn_end_row = len(summary_data) - 1
        total_row = hsn_end_row + 1
        summary_data.append(['TOTAL', f'{grand_taxable:.2f}', '', f'{grand_tax:.2f}'])

        summary_table = Table(summary_data, colWidths=summary_col_widths)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, total_row), 0.5, colors.grey),
            ('ALIGN', (1, 0), (-1, total_row), 'RIGHT'),
            ('FONTNAME', (0, total_row), (-1, total_row), 'Helvetica-Bold'),
        ]))
        elements.append(summary_table)

        grand_box_data = [
            ['Amount Chargeable [In Words]', 'GRAND TOTAL', f'Rs. {grand_total_rounded}'],
            [amount_to_words(grand_total_rounded), '', 'E. & O. E.'],
        ]
        grand_box_widths = [127, 206, 138]
        grand_box_table = Table(grand_box_data, colWidths=grand_box_widths)
        grand_box_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (1, 0), (1, 0), 11),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('FONTNAME', (2, 0), (2, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (2, 0), (2, 0), 11),
            ('ALIGN', (2, 1), (2, 1), 'RIGHT'),
            ('FONTNAME', (2, 1), (2, 1), 'Helvetica-Bold'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(grand_box_table)
    else:
        summary_col_widths = [147, 74, 45, 56, 45, 56, 48]
        summary_data = [
            ['HSN / SAC', 'Taxable Value', 'Central Tax', '', 'State Tax', '', 'Total Tax Amount'],
            ['', '', 'Rate', 'Amount', 'Rate', 'Amount', ''],
        ]

        for (gst_percent, is_exempt), vals in hsn_summary.items():
            half_rate = 0 if is_exempt else gst_percent / 2
            half_amt = vals['gst'] / 2
            hsn_list = ', '.join(sorted(vals['hsns']))
            summary_data.append([
                hsn_list, f"{vals['taxable']:.2f}",
                'Exempt' if is_exempt else f'{half_rate}%', f'{half_amt:.2f}',
                'Exempt' if is_exempt else f'{half_rate}%', f'{half_amt:.2f}',
                f"{vals['gst']:.2f}"
            ])

        hsn_end_row = len(summary_data) - 1
        total_row = hsn_end_row + 1
        summary_data.append(['TOTAL', f'{grand_taxable:.2f}', '', f'{grand_tax / 2:.2f}', '', f'{grand_tax / 2:.2f}', f'{grand_tax:.2f}'])

        summary_table = Table(summary_data, colWidths=summary_col_widths)
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#343a40')),
            ('TEXTCOLOR', (0, 0), (-1, 1), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, total_row), 0.5, colors.grey),
            ('ALIGN', (1, 0), (-1, total_row), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, 1), 'MIDDLE'),
            ('SPAN', (0, 0), (0, 1)),
            ('SPAN', (1, 0), (1, 1)),
            ('SPAN', (2, 0), (3, 0)),
            ('SPAN', (4, 0), (5, 0)),
            ('SPAN', (6, 0), (6, 1)),
            ('ALIGN', (2, 0), (5, 0), 'CENTER'),
            ('FONTNAME', (0, total_row), (-1, total_row), 'Helvetica-Bold'),
        ]))
        elements.append(summary_table)

        grand_box_data = [
            ['Amount Chargeable [In Words]', 'GRAND TOTAL', f'Rs. {grand_total_rounded}'],
            [amount_to_words(grand_total_rounded), '', 'E. & O. E.'],
        ]
        grand_box_widths = [127, 206, 138]
        grand_box_table = Table(grand_box_data, colWidths=grand_box_widths)
        grand_box_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (1, 0), (1, 0), 11),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('FONTNAME', (2, 0), (2, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (2, 0), (2, 0), 11),
            ('ALIGN', (2, 1), (2, 1), 'RIGHT'),
            ('FONTNAME', (2, 1), (2, 1), 'Helvetica-Bold'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(grand_box_table)

    elements.append(Spacer(1, 30))

    sign_table = Table([['Books Checked By', f'For, {STORE_NAME}']], colWidths=[250, 250])
    sign_table.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
    elements.append(sign_table)

    return elements


def generate_bill_pdf(bill):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=10 * mm, bottomMargin=10 * mm, leftMargin=12 * mm, rightMargin=12 * mm)
    elements = build_invoice_elements(bill)
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_bill_pdf_three_copies(bill):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=10 * mm, bottomMargin=10 * mm, leftMargin=12 * mm, rightMargin=12 * mm)

    labels = ['Office Copy', 'Store Copy', 'Customer Copy']
    all_elements = []
    for i, label in enumerate(labels):
        all_elements.extend(build_invoice_elements(bill, copy_label=label))
        if i < len(labels) - 1:
            all_elements.append(PageBreak())

    doc.build(all_elements)
    buffer.seek(0)
    return buffer


def generate_report_pdf(period, ref_date, data, city_label):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, spaceAfter=2)
    normal = styles['Normal']

    elements = []
    elements.append(Paragraph(STORE_NAME, title_style))
    elements.append(Paragraph(f"{period.capitalize()} Stock Report — {city_label}", normal))
    elements.append(Paragraph(f"Period: {data['start'].strftime('%d-%m-%Y')} to {data['end'].strftime('%d-%m-%Y')}", normal))
    elements.append(Spacer(1, 15))

    summary_data = [['Total Bills', str(data['total_bills'])], ['Total Amount', f"Rs. {data['total_amount']:.2f}"]]
    summary_table = Table(summary_data, colWidths=[150, 150])
    summary_table.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
    elements.append(summary_table)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("Stock Overview", styles['Heading3']))
    stock_table_data = [['Sr.No', 'Product', 'Year', 'MRP', 'Opening', 'Inward', 'Current', 'Sales', 'Closing']]
    for idx, s in enumerate(data['stock_overview'], start=1):
        stock_table_data.append([
            str(idx), s['name'], s.get('year') or '-', f"{s.get('price', 0)}",
            str(s['opening_stock']), str(s['inward_stock']),
            str(s['current_stock']), str(s['sales']), str(s['closing_stock'])
        ])
    stock_table = Table(stock_table_data, colWidths=[30, 140, 40, 45, 45, 45, 45, 40, 45])
    stock_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(stock_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_gst_report_pdf(period, start_date, data, city_label):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('GstTitle', parent=styles['Heading2'], fontSize=13, alignment=1)

    elements = []
    elements.append(Paragraph(f"{STORE_NAME} - GST REPORT - {city_label}", title_style))
    elements.append(Paragraph(f"{data['start'].strftime('%d-%m-%Y')} to {data['end'].strftime('%d-%m-%Y')}", styles['Normal']))
    elements.append(Spacer(1, 10))

    summary_data = [
        ['Taxable Value', 'Total CGST', 'Total SGST', 'Grand Total'],
        [f"Rs. {data['total_taxable']:.2f}", f"Rs. {data['total_cgst']:.2f}", f"Rs. {data['total_sgst']:.2f}", f"Rs. {data['grand_total']:.2f}"]
    ]
    summary_table = Table(summary_data, colWidths=[130, 130, 130, 130])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 15))

    table_data = [['Bill No.', 'Date', 'Taxable Value', 'CGST', 'SGST', 'Total GST', 'Grand Total']]
    for row in data['bill_rows']:
        table_data.append([
            row['bill_number'], row['date'].strftime('%d-%m-%Y %H:%M'),
            f"{row['taxable']:.2f}", f"{row['cgst']:.2f}", f"{row['sgst']:.2f}",
            f"{row['total_gst']:.2f}", f"{row['grand_total']:.2f}"
        ])

    bill_table = Table(table_data, colWidths=[80, 90, 75, 65, 65, 70, 75])
    bill_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343a40')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
    ]))
    elements.append(bill_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_day_wise_pdf(data, city_label):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), topMargin=10 * mm, bottomMargin=10 * mm, leftMargin=10 * mm, rightMargin=10 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('DayWiseTitle', parent=styles['Heading2'], fontSize=13, alignment=1)

    elements = []
    date_label = data['start'].strftime('%d-%m-%Y') if data['start'].date() == data['end'].date() else f"{data['start'].strftime('%d-%m-%Y')} to {data['end'].strftime('%d-%m-%Y')}"
    elements.append(Paragraph(
        f"{STORE_NAME} - SALES REPORT - {date_label} ({city_label})",
        title_style
    ))
    elements.append(Spacer(1, 8))

    rates = data['rates']
    header = ['Sr.', 'Date', 'Invoice No.', 'Student Name', 'Class', 'Payment Mode', 'Exempt Amt']
    for r in rates:
        header.append(f'Taxable @{r}%')
    for r in rates:
        header.append(f'GST @{r}%')
    header.append('Grand Total')

    table_data = [header]

    for row in data['rows']:
        line = [
            str(row['sr_no']), row['date'].strftime('%d-%m-%Y'), row['bill_number'],
            row['student_name'], row['student_class'], row['payment_mode'],
            f"{row['exempt_amt']:.2f}"
        ]
        for r in rates:
            line.append(f"{row['taxable_by_rate'].get(r, 0):.2f}")
        for r in rates:
            line.append(f"{row['gst_by_rate'].get(r, 0):.2f}")
        line.append(f"{row['grand_total']:.2f}")
        table_data.append(line)

    total_line = ['', '', '', '', '', 'TOTAL', f"{data['total_exempt']:.2f}"]
    for r in rates:
        total_line.append(f"{data['total_taxable_by_rate'].get(r, 0):.2f}")
    for r in rates:
        total_line.append(f"{data['total_gst_by_rate'].get(r, 0):.2f}")
    total_line.append(f"{data['total_grand']:.2f}")
    table_data.append(total_line)
    total_row_idx = len(table_data) - 1

    n_extra_cols = 1 + len(rates) * 2 + 1
    base_widths = [30, 55, 70, 110, 40, 65]
    remaining_width = 780 - sum(base_widths)
    extra_width = remaining_width / n_extra_cols if n_extra_cols else 0
    col_widths = base_widths + [extra_width] * n_extra_cols

    day_table = Table(table_data, colWidths=col_widths)
    day_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E7A46')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (6, 0), (-1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 1), (-1, total_row_idx - 1), colors.HexColor('#E7F3EA')),
        ('BACKGROUND', (-1, 1), (-1, total_row_idx), colors.HexColor('#FBE0CE')),
        ('FONTNAME', (0, total_row_idx), (-1, total_row_idx), 'Helvetica-Bold'),
        ('BACKGROUND', (0, total_row_idx), (-1, total_row_idx), colors.HexColor('#D9A441')),
    ]))
    elements.append(day_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_credit_note_pdf(return_record):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm, leftMargin=15 * mm, rightMargin=15 * mm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('CNTitle', parent=styles['Heading2'], fontSize=14, alignment=1)
    elements = []

    city = return_record.city
    school_line = city.name if city else STORE_NAME
    extra_line = city.extra_counter_line if city and city.extra_counter_line else STORE_EXTRA_LINE

    elements.append(Paragraph(STORE_NAME, styles['Heading2']))
    elements.append(Paragraph(STORE_ADDRESS, styles['Normal']))
    elements.append(Paragraph(f"School / Branch: {school_line}", styles['Normal']))
    elements.append(Paragraph(extra_line, styles['Normal']))
    active_gstin = city.gstin_number if city and city.gstin_number else STORE_GSTIN
    elements.append(Paragraph(f"GSTIN NO. {active_gstin}", styles['Normal']))
    elements.append(Spacer(1, 10))
    elements.append(Paragraph('<u>CREDIT NOTE</u>', title_style))
    elements.append(Spacer(1, 8))

    bill = return_record.bill
    issued_by = return_record.recorded_by.username if return_record.recorded_by else '-'
    meta_data = [
        ['Credit Note No.:', return_record.credit_note_number, 'Date:', return_record.created_at.strftime('%d-%m-%Y')],
        ['Against Invoice:', bill.bill_number, 'Invoice Date:', bill.created_at.strftime('%d-%m-%Y')],
        ['Student Name:', bill.student_name or '-', 'Class:', to_roman(bill.student_class) if bill.student_class else '-'],
        ['Admission No.:', bill.admission_number or '-', 'Processed By:', issued_by],
    ]
    meta_table = Table(meta_data, colWidths=[100, 150, 80, 150])
    meta_table.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    table_data = [['S.No', 'Particulars', 'HSN', 'Qty', 'Rate', 'GST%', 'Amount']]
    grand_total = 0
    for idx, item in enumerate(return_record.items, start=1):
        gst_display = 'Exempt' if item.is_gst_exempt else f'{item.gst_percent}%'
        table_data.append([
            str(idx), item.product_name, item.hsn_number or '-',
            str(item.quantity_returned), f'{item.price:.2f}', gst_display, f'{item.total_amount}'
        ])
        grand_total += item.total_amount

    table_data.append(['', '', '', '', '', 'TOTAL', f'{grand_total}'])
    total_row_idx = len(table_data) - 1

    items_table = Table(table_data, colWidths=[26, 160, 55, 35, 55, 45, 65])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8B0000')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, total_row_idx), (-1, total_row_idx), 'Helvetica-Bold'),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 10))

    if return_record.reason:
        elements.append(Paragraph(f"<b>Reason:</b> {return_record.reason}", styles['Normal']))
        elements.append(Spacer(1, 10))

    elements.append(Paragraph(f"<b>Total Refund/Credit Amount: Rs. {grand_total}</b>", styles['Normal']))
    elements.append(Spacer(1, 20))

    sign_table = Table([['Received By (Parent Signature)', f'For, {STORE_NAME}']], colWidths=[250, 250])
    sign_table.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
    elements.append(sign_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer
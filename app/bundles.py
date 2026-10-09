from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Bundle, BundleItem, Product
from app.inventory import store_staff_required
from app.city_utils import get_active_city_id
from app.class_options import CLASS_OPTIONS
from app.pdf_utils import to_roman
from app.bundle_rules import compulsory_classes, set_compulsory_for_class

bundles_bp = Blueprint('bundles_bp', __name__, url_prefix='/inventory/bundles')


def get_or_create_bundle(city_id, applicable_class):
    bundle = Bundle.query.filter_by(city_id=city_id, applicable_class=applicable_class).first()
    if not bundle:
        bundle = Bundle(city_id=city_id, applicable_class=applicable_class)
        db.session.add(bundle)
        db.session.commit()
    return bundle


@bundles_bp.route('/')
@login_required
@store_staff_required
def bundle_list():
    city_id = get_active_city_id()
    summary = []
    for c in CLASS_OPTIONS:
        bundle = Bundle.query.filter_by(city_id=city_id, applicable_class=c).first()
        count = len(bundle.items) if bundle else 0
        summary.append({'class_value': c, 'label': to_roman(c), 'count': count})
    return render_template('bundles/list.html', summary=summary)


@bundles_bp.route('/<class_value>', methods=['GET', 'POST'])
@login_required
@store_staff_required
def bundle_edit(class_value):
    city_id = get_active_city_id()
    bundle = get_or_create_bundle(city_id, class_value)

    if request.method == 'POST':
        product_id = request.form.get('product_id')
        quantity = request.form.get('quantity', '1').strip()
        if not product_id:
            flash('Select a product to add')
            return redirect(url_for('bundles_bp.bundle_edit', class_value=class_value))
        try:
            quantity = int(quantity)
        except ValueError:
            quantity = 1

        product = Product.query.get(int(product_id))
        if not product or product.city_id != city_id:
            flash('Invalid product')
            return redirect(url_for('bundles_bp.bundle_edit', class_value=class_value))

        existing_item = BundleItem.query.filter_by(bundle_id=bundle.id, product_id=product.id).first()
        if existing_item:
            existing_item.quantity = quantity
            flash(f'Updated "{product.name}" quantity to {quantity}')
        else:
            db.session.add(BundleItem(bundle_id=bundle.id, product_id=product.id, quantity=quantity))
            flash(f'"{product.name}" added to Class {to_roman(class_value)} bundle')
        db.session.commit()
        return redirect(url_for('bundles_bp.bundle_edit', class_value=class_value))

    # only show products that belong to this class, or are Common Items (applicable_class is None)
    eligible_products = Product.query.filter(
        Product.city_id == city_id,
        Product.is_active == True,
        db.or_(
            Product.applicable_class == class_value,
            Product.applicable_class.is_(None),
            Product.applicable_class.in_(['notebook', 'extra', 'stationary'])
        )
    ).order_by(Product.name).all()
    class_items = [p for p in eligible_products if p.applicable_class == class_value]
    common_items = [p for p in eligible_products if p.applicable_class is None]
    stationary_items = [p for p in eligible_products if p.applicable_class in ('extra', 'stationary')]
    notebook_items = [p for p in eligible_products if p.applicable_class == 'notebook']

    grouped_products = [
        {'label': f'Class {to_roman(class_value)} Items', 'products': class_items},
        {'label': 'Common Items', 'products': common_items},
        {'label': 'Stationary', 'products': stationary_items},
        {'label': 'Notebook', 'products': notebook_items},
    ]

    bundle_items_map = {i.product_id: i for i in bundle.items}
    compulsory_ids = {i.product_id for i in bundle.items if i.product and class_value in compulsory_classes(i.product)}

    # group 'Current Bundle Contents' by section so staff can scan it easily
    deleted_label = 'Deleted Products — please remove these'
    contents_labels = [f'Class {to_roman(class_value)} Textbooks', 'Common Items', 'Stationary', 'Notebook', 'Other', deleted_label]
    contents_buckets = {lbl: [] for lbl in contents_labels}
    for i in bundle.items:
        p = i.product
        if p is None:
            lbl = deleted_label
        elif p.applicable_class == class_value:
            lbl = contents_labels[0]
        elif p.applicable_class is None:
            lbl = 'Common Items'
        elif p.applicable_class in ('extra', 'stationary'):
            lbl = 'Stationary'
        elif p.applicable_class == 'notebook':
            lbl = 'Notebook'
        else:
            lbl = 'Other'
        contents_buckets[lbl].append(i)
    contents_groups = [
        {'label': lbl, 'rows': sorted(contents_buckets[lbl], key=lambda i: i.product.name.lower() if i.product else '')}
        for lbl in contents_labels if contents_buckets[lbl]
    ]

    return render_template('bundles/edit.html', bundle=bundle, class_value=class_value,
                            label=to_roman(class_value), grouped_products=grouped_products,
                            bundle_items_map=bundle_items_map, compulsory_ids=compulsory_ids,
                            contents_groups=contents_groups)


@bundles_bp.route('/item/<int:item_id>/remove', methods=['POST'])
@login_required
@store_staff_required
def remove_bundle_item(item_id):
    item = BundleItem.query.get_or_404(item_id)
    bundle = item.bundle
    if bundle.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('bundles_bp.bundle_list'))
    class_value = bundle.applicable_class
    if item.product:
        set_compulsory_for_class(item.product, class_value, False)
    db.session.delete(item)
    db.session.commit()
    flash('Item removed from bundle')
    return redirect(url_for('bundles_bp.bundle_edit', class_value=class_value))


@bundles_bp.route('/item/<int:item_id>/compulsory', methods=['POST'])
@login_required
@store_staff_required
def toggle_bundle_item_compulsory(item_id):
    item = BundleItem.query.get_or_404(item_id)
    bundle = item.bundle
    if bundle.city_id != get_active_city_id():
        flash('Access denied')
        return redirect(url_for('bundles_bp.bundle_list'))
    if not item.product:
        flash('This product no longer exists')
        return redirect(url_for('bundles_bp.bundle_edit', class_value=bundle.applicable_class))

    is_compulsory = request.form.get('compulsory') == 'on'
    set_compulsory_for_class(item.product, bundle.applicable_class, is_compulsory)
    db.session.commit()
    if request.headers.get('X-Requested-With') == 'fetch':
        return jsonify({'ok': True, 'compulsory': is_compulsory})
    flash(f'"{item.product.name}" is now {"compulsory" if is_compulsory else "optional"} in the custom bundle (Option 2)')
    return redirect(url_for('bundles_bp.bundle_edit', class_value=bundle.applicable_class))
from app import db
from app.models import Bundle, Product


def compulsory_classes(product):
    """Class values for which this product is ticked 'compulsory in custom bundle' (Option 2)."""
    raw = product.needed_for_class or ''
    return {c.strip() for c in raw.split(',') if c.strip()}


def set_compulsory_for_class(product, class_value, is_compulsory):
    classes = compulsory_classes(product)
    if is_compulsory:
        classes.add(class_value)
    else:
        classes.discard(class_value)
    product.needed_for_class = ','.join(sorted(classes)) or None


def get_custom_shop_items(city_id, student_class):
    """
    Option 2 (custom bundle) for one class.
    Uses that class's bundle. If no bundle is set up yet, falls back to the old behaviour
    (all class textbooks + all common/stationary items).
      compulsory = class textbooks + items staff ticked as compulsory
      electives  = optional subjects (French, Sanskrit, ...) — parent ticks the one(s) that apply
      optional   = everything else in the bundle
    """
    city_id = int(city_id)
    result = {'compulsory': [], 'electives': [], 'optional': [], 'from_bundle': False}

    bundle = Bundle.query.filter_by(city_id=city_id, applicable_class=student_class).first()
    entries = []
    if bundle and bundle.items:
        result['from_bundle'] = True
        for bi in bundle.items:
            p = bi.product
            if p and p.is_active and p.city_id == city_id:
                entries.append((p, bi.quantity or 1))
    else:
        products = Product.query.filter(
            Product.city_id == city_id,
            Product.is_active == True,
            db.or_(
                Product.applicable_class == student_class,
                Product.applicable_class.is_(None),
                Product.applicable_class.in_(['notebook', 'extra', 'stationary'])
            )
        ).order_by(Product.product_type, Product.name).all()
        entries = [(p, 1) for p in products]

    for p, qty in entries:
        entry = {'product': p, 'quantity': qty, 'in_stock': (p.stock_quantity or 0) >= qty}
        if p.is_elective:
            result['electives'].append(entry)
        elif p.applicable_class == student_class or student_class in compulsory_classes(p):
            result['compulsory'].append(entry)
        else:
            result['optional'].append(entry)

    return result
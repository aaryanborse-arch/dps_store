from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


# association table: additional cities a store_staff user can switch into
user_cities = db.Table(
    'user_cities',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('city_id', db.Integer, db.ForeignKey('cities.id'), primary_key=True)
)


class City(db.Model):
    __tablename__ = 'cities'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    extra_counter_line = db.Column(db.String(255), nullable=True)
    invoice_prefix = db.Column(db.String(50), nullable=True)
    next_invoice_number = db.Column(db.Integer, nullable=True)
    bundle_enabled = db.Column(db.Boolean, default=True, nullable=False)
    individual_items_enabled = db.Column(db.Boolean, default=True, nullable=False)
    free_shopping_enabled = db.Column(db.Boolean, default=True, nullable=False)
    jodo_component_code = db.Column(db.String(50), nullable=True)
    jodo_branch_code = db.Column(db.String(50), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    gstin_number = db.Column(db.String(20), nullable=True)
    next_credit_note_number = db.Column(db.Integer, default=1, nullable=True)


    def __repr__(self):
        return f'<City {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(20), nullable=False)

    # primary/default city
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=True)
    city = db.relationship('City', foreign_keys=[city_id], backref='primary_staff')

    # additional cities this user can switch into (store_staff only)
    accessible_cities = db.relationship('City', secondary=user_cities, backref='staff_members')

    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def all_cities(self):
        """primary city + additional accessible cities, deduplicated, primary first"""
        cities = [c for c in self.accessible_cities]
        if self.city and self.city not in cities:
            cities.insert(0, self.city)
        return cities

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    year = db.Column(db.String(20), nullable=True)
    hsn_number = db.Column(db.String(20), nullable=False)
    is_elective = db.Column(db.Boolean, default=False)
    gst_percent = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product_type = db.Column(db.String(20), nullable=False)
    applicable_class = db.Column(db.String(20), nullable=True)
    publisher_name = db.Column(db.String(150), nullable=True)
    subject = db.Column(db.String(100), nullable=True)
    is_gst_exempt = db.Column(db.Boolean, default=False)
    needed_for_class = db.Column(db.String(255), nullable=True)  # comma-separated class keys
    deactivated_at = db.Column(db.DateTime, nullable=True)
    group_name = db.Column(db.String(150), nullable=True, index=True)

    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False , index=True)
    city = db.relationship('City', backref='products')

    stock_quantity = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_low_stock(self):
        return self.stock_quantity <= self.low_stock_threshold

    def __repr__(self):
        return f'<Product {self.name} - {self.city.name if self.city else "?"}>'


class Bill(db.Model):
    __tablename__ = 'bills'

    id = db.Column(db.Integer, primary_key=True)
    bill_number = db.Column(db.String(30), unique=True, nullable=False)
    sale_type = db.Column(db.String(10), nullable=False, default='offline')
    payment_method = db.Column(db.String(20), nullable=True)

    
    admission_number = db.Column(db.String(50), nullable=False, index=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False, index=True)
    city = db.relationship('City', backref='bills')

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by = db.relationship('User', backref='bills')

    buyer_name = db.Column(db.String(150), nullable=False)
    buyer_phone = db.Column(db.String(20), nullable=False)
    student_name = db.Column(db.String(150), nullable=True)
    student_class = db.Column(db.String(20), nullable=True)

    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Bill {self.bill_number}>'


class BillItem(db.Model):
    __tablename__ = 'bill_items'

    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    bill = db.relationship('Bill', backref='items')
    is_gst_exempt = db.Column(db.Boolean, default=False)
    publisher_name = db.Column(db.String(150), nullable=True)
    subject = db.Column(db.String(100), nullable=True)

    # link back to the real product for reporting (nullable — old rows won't have it)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)

    # snapshot fields — captured at time of sale
    product_name = db.Column(db.String(150), nullable=False)
    hsn_number = db.Column(db.String(20), nullable=False)
    gst_percent = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False)

    quantity = db.Column(db.Integer, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<BillItem {self.product_name} x{self.quantity}>'


class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, nullable=False)
    otp_code = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)
    admission_number = db.Column(db.String(50), nullable=True)
    payment_method = db.Column(db.String(20), nullable=True)
    

    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False ,index=True)
    city = db.relationship('City', backref='orders')

    parent_name = db.Column(db.String(150), nullable=False)
    parent_phone = db.Column(db.String(20), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    student_class = db.Column(db.String(20), nullable=False)

    total_amount = db.Column(db.Float, nullable=False, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collected_at = db.Column(db.DateTime, nullable=True)

    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=True)
    bill = db.relationship('Bill', backref='source_order')

    def __repr__(self):
        return f'<Order {self.order_number} - {self.status}>'


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    order = db.relationship('Order', backref='items')

    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product')

    product_name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<OrderItem {self.product_name} x{self.quantity}>'


class StockLog(db.Model):
    __tablename__ = 'stock_logs'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product')
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    quantity_added = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def __repr__(self):
        return f'<StockLog product={self.product_id} +{self.quantity_added}>'

class Issuance(db.Model):
    __tablename__ = 'issuances'

    id = db.Column(db.Integer, primary_key=True)

    # optional link — only set if issued via the teacher self-service login
        # optional link — only set if issued via the teacher self-service login
    teacher_id = db.Column(db.String(50), nullable=False, index=True)

    # manual entry fields — used when store staff records a walk-in teacher
    teacher_name = db.Column(db.String(150), nullable=True)
    teacher_employee_id = db.Column(db.String(50), nullable=True)

    recorded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    recorded_by = db.relationship('User', foreign_keys=[recorded_by_id])

    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False, index=True)
    city = db.relationship('City', backref='city_issuances')

    status = db.Column(db.String(20), default='issued')  # 'issued' or 'returned'
    returned_at = db.Column(db.DateTime, nullable=True)

    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(150), nullable=False)

    quantity = db.Column(db.Integer, nullable=False)
    student_name = db.Column(db.String(150), nullable=True)
    student_class = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.String(255), nullable=True)

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)

    def teacher_display_name(self):
        return self.teacher_name or 'Unknown'

    def __repr__(self):
        return f'<Issuance {self.product_name} x{self.quantity}>'   

class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Supplier {self.name}>'


class PurchaseRecord(db.Model):
    __tablename__ = 'purchase_records'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    supplier = db.relationship('Supplier', backref='purchase_records')
    invoice_number = db.Column(db.String(100), nullable=True)
    invoice_date = db.Column(db.Date, nullable=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='purchase_records')
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by = db.relationship('User')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


    def __repr__(self):
        return f'<PurchaseRecord {self.invoice_number}>'

    def total_taxable(self):
        return round(sum(i.taxable_value() for i in self.items), 2)

    def total_gst(self):
        return round(sum(i.gst_amount() for i in self.items), 2)

    def total_amount(self):
        return round(sum(i.total_amount() for i in self.items), 2)


class PurchaseRecordItem(db.Model):
    __tablename__ = 'purchase_record_items'
    id = db.Column(db.Integer, primary_key=True)
    purchase_record_id = db.Column(db.Integer, db.ForeignKey('purchase_records.id'), nullable=False)
    purchase_record = db.relationship('PurchaseRecord', backref='items')
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(150), nullable=False)
    invoiced_qty = db.Column(db.Integer, nullable=False)
    received_qty = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    gst_percent = db.Column(db.Float, nullable=False, default=0.0)
    is_gst_exempt = db.Column(db.Boolean, default=False)

    def has_discrepancy(self):
        return self.invoiced_qty != self.received_qty

    def taxable_value(self):
        return self.received_qty * self.price

    def gst_amount(self):
        return 0.0 if self.is_gst_exempt else round(self.taxable_value() * self.gst_percent / 100, 2)

    def total_amount(self):
        return round(self.taxable_value() + self.gst_amount(), 2)

class Bundle(db.Model):
    __tablename__ = 'bundles'
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='bundles')
    applicable_class = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def total_price(self):
        return round(sum(i.product.price * i.quantity for i in self.items if i.product), 2)


class BundleItem(db.Model):
    __tablename__ = 'bundle_items'
    id = db.Column(db.Integer, primary_key=True)
    bundle_id = db.Column(db.Integer, db.ForeignKey('bundles.id'), nullable=False)
    bundle = db.relationship('Bundle', backref='items')
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product = db.relationship('Product')
    quantity = db.Column(db.Integer, nullable=False, default=1)

class StudentRecord(db.Model):
    __tablename__ = 'student_records'
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='student_records')
    admission_number = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    student_class = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CouponOrder(db.Model):
    __tablename__ = 'coupon_orders'
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='coupon_orders')
    admission_number = db.Column(db.String(50), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    student_class = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    otp_code = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending' or 'collected'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collected_at = db.Column(db.DateTime, nullable=True)
    collected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    collected_by = db.relationship('User')

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user = db.relationship('User')
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=True)
    city = db.relationship('City')
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PurchaseInvoiceUpload(db.Model):
    __tablename__ = 'purchase_invoice_uploads'
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City')
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_by = db.relationship('User')
    vendor_name = db.Column(db.String(200), nullable=False)
    invoice_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.String(500), nullable=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_mimetype = db.Column(db.String(100), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class TeacherRecord(db.Model):
    __tablename__ = 'teacher_records'
    id = db.Column(db.Integer, primary_key=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City', backref='teacher_records')
    teacher_id = db.Column(db.String(50), nullable=False)
    teacher_name = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PendingJodoOrder(db.Model):
    __tablename__ = 'pending_jodo_orders'
    id = db.Column(db.Integer, primary_key=True)
    jodo_order_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    parent_name = db.Column(db.String(150), nullable=False)
    parent_phone = db.Column(db.String(20), nullable=False)
    parent_email = db.Column(db.String(150), nullable=False)
    student_name = db.Column(db.String(150), nullable=False)
    student_class = db.Column(db.String(20), nullable=False)
    admission_number = db.Column(db.String(50), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    cart_snapshot = db.Column(db.Text, nullable=False)  # JSON string: {product_id: qty}
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'completed', 'failed'
    resulting_order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ReturnRecord(db.Model):
    __tablename__ = 'return_records'
    id = db.Column(db.Integer, primary_key=True)
    credit_note_number = db.Column(db.String(100), unique=True, nullable=False)
    bill_id = db.Column(db.Integer, db.ForeignKey('bills.id'), nullable=False)
    bill = db.relationship('Bill')
    city_id = db.Column(db.Integer, db.ForeignKey('cities.id'), nullable=False)
    city = db.relationship('City')
    recorded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    recorded_by = db.relationship('User')
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ReturnRecordItem(db.Model):
    __tablename__ = 'return_record_items'
    id = db.Column(db.Integer, primary_key=True)
    return_record_id = db.Column(db.Integer, db.ForeignKey('return_records.id'), nullable=False)
    return_record = db.relationship('ReturnRecord', backref='items')
    bill_item_id = db.Column(db.Integer, db.ForeignKey('bill_items.id'), nullable=False)
    bill_item = db.relationship('BillItem')
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    product_name = db.Column(db.String(150), nullable=False)
    hsn_number = db.Column(db.String(50), nullable=True)
    quantity_returned = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    gst_percent = db.Column(db.Float, default=0.0)
    is_gst_exempt = db.Column(db.Boolean, default=False)
    taxable_amount = db.Column(db.Float, nullable=False)
    gst_amount = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
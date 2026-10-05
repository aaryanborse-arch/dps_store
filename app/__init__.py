from flask import Flask, app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, current_user
import os

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)

    database_url = os.environ.get('DATABASE_URL', 'sqlite:///store.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    if database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-later')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.city_utils import get_active_city

    @app.context_processor
    def inject_active_city():
        if current_user.is_authenticated and current_user.role == 'store_staff':
            return {'active_city': get_active_city()}
        return {}

    from app.pdf_utils import to_roman
    app.jinja_env.filters['roman'] = to_roman

    from app.routes import main
    app.register_blueprint(main)

    from app.auth import auth
    app.register_blueprint(auth)

    from app.admin import admin
    app.register_blueprint(admin)

    from app.inventory import inventory
    app.register_blueprint(inventory)

    from app.sales import sales
    app.register_blueprint(sales)

    from app.parent import parent
    app.register_blueprint(parent)

    from app.reports import reports
    app.register_blueprint(reports)

    from app.teacher import teacher_bp
    app.register_blueprint(teacher_bp)

    from app.supplier_import import supplier_import
    app.register_blueprint(supplier_import)

    from app.vendors import vendors
    app.register_blueprint(vendors)

    from app.bundles import bundles_bp
    app.register_blueprint(bundles_bp)

    from app.students import students_bp
    app.register_blueprint(students_bp)

    from app.coupons import coupons
    app.register_blueprint(coupons)

    from app.school_catalog_import import catalog_import
    app.register_blueprint(catalog_import)

    from app.purchase_invoices import purchase_invoices
    app.register_blueprint(purchase_invoices)

    from app.teachers_list import teachers_list_bp
    app.register_blueprint(teachers_list_bp)

    from app.returns import returns_bp
    app.register_blueprint(returns_bp)

    return app
from app import create_app, db
from app.models import User

app = create_app()

with app.app_context():
    existing = User.query.filter_by(username='admin').first()
    if existing:
        print("Admin already exists.")
    else:
        admin = User(username='admin', role='super_admin', city_id=None)
        admin.set_password('admin123')  # change this later, this is just for dev
        db.session.add(admin)
        db.session.commit()
        print("Super Admin created: username='admin', password='admin123'")
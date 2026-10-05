from flask_login import current_user
from app import db
from app.models import ActivityLog


def log_activity(action, details=None):
    try:
        entry = ActivityLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            city_id=getattr(current_user, 'city_id', None) if current_user.is_authenticated else None,
            action=action,
            details=details
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
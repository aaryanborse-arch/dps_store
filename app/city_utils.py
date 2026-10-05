from flask import session
from flask_login import current_user


def get_active_city_id():
    """The city a store_staff user is currently operating in (session override, else their primary city)."""
    if current_user.is_authenticated and current_user.role == 'store_staff':
        return session.get('active_city_id', current_user.city_id)
    return current_user.city_id if current_user.is_authenticated else None


def get_active_city():
    from app.models import City
    city_id = get_active_city_id()
    return City.query.get(city_id) if city_id else None
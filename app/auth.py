from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User
from app.city_utils import get_active_city_id, get_active_city

auth = Blueprint('auth', __name__)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            session.pop('active_city_id', None)

            if user.role == 'store_staff' and len(user.all_cities()) > 1:
                return redirect(url_for('auth.select_active_city'))

            return redirect(url_for('auth.dashboard'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('auth.login'))

    return render_template('login.html')


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('active_city_id', None)
    return redirect(url_for('auth.login'))


@auth.route('/switch-city/<int:city_id>')
@login_required
def switch_city(city_id):
    if current_user.role != 'store_staff':
        return redirect(url_for('auth.dashboard'))

    allowed_ids = {c.id for c in current_user.all_cities()}
    if city_id not in allowed_ids:
        flash('You do not have access to that school')
        return redirect(url_for('auth.dashboard'))

    session['active_city_id'] = city_id
    flash('Switched school')
    return redirect(url_for('auth.dashboard'))

@auth.route('/select-city', methods=['GET', 'POST'])
@login_required
def select_active_city():
    if current_user.role != 'store_staff':
        return redirect(url_for('auth.dashboard'))

    cities = current_user.all_cities()
    if len(cities) <= 1:
        return redirect(url_for('auth.dashboard'))

    if request.method == 'POST':
        city_id = request.form.get('city_id')
        allowed_ids = {c.id for c in cities}
        if not city_id or int(city_id) not in allowed_ids:
            flash('Please select a valid city')
            return redirect(url_for('auth.select_active_city'))

        session['active_city_id'] = int(city_id)
        return redirect(url_for('auth.dashboard'))

    return render_template('select_city.html', cities=cities)


@auth.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'super_admin':
        return render_template('dashboard_super_admin.html')

    elif current_user.role == 'store_staff':
        cities = current_user.all_cities()
        active_city = get_active_city()
        active_city_id = get_active_city_id()
        return render_template('dashboard_store_staff.html', cities=cities, active_city=active_city, active_city_id=active_city_id)

    elif current_user.role == 'teacher':
        return render_template('dashboard_teacher.html')

    else:
        return "Unknown role"
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime
import os
import cv2
import numpy as np
from pyzbar.pyzbar import decode
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mot-chiec-key-bi-mat'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, role='renter'):
        self.id = id
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    if str(user_id).startswith('admin_'):
        return User(user_id, role='admin')
    user = MotorbikeUser.query.get(int(user_id))
    if user:
        return User(user.id, role='renter')
    return None

UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
db_path = os.path.join(os.path.dirname(__file__), 'motorbike_rental.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
db = SQLAlchemy(app)

class MotorbikeUser(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20))
    name          = db.Column(db.String(100))
    cccd          = db.Column(db.String(20))
    phone         = db.Column(db.String(15))
    profile_img   = db.Column(db.String(100))
    start_time    = db.Column(db.DateTime, default=datetime.now)
    lat           = db.Column(db.Float, default=10.7769)
    lng           = db.Column(db.Float, default=106.7009)
    speed         = db.Column(db.Float, default=0.0)        
    theft_alert   = db.Column(db.Boolean, default=False)    
    is_fallen     = db.Column(db.Boolean, default=False)    
    updated_at    = db.Column(db.DateTime, default=datetime.now)

class LocationHistory(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('motorbike_user.id'), nullable=False)
    lat       = db.Column(db.Float, nullable=False)
    lng       = db.Column(db.Float, nullable=False)
    district  = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)

TPHCM_DISTRICTS = {
    "Quận 1": [[10.7890, 106.6900], [10.7935, 106.7055], [10.7745, 106.7130], [10.7620, 106.6990], [10.7675, 106.6850], [10.7780, 106.6810]],
    "Quận 3": [[10.7890, 106.6900], [10.7780, 106.6810], [10.7675, 106.6850], [10.7690, 106.6660], [10.7845, 106.6730]],
    "Thành phố Thủ Đức": [[10.8750, 106.7800], [10.8900, 106.8400], [10.8000, 106.8500], [10.7550, 106.7800], [10.7650, 106.7400], [10.8200, 106.7100]],
    "Quận 4": [[10.7675, 106.6850], [10.7620, 106.6990], [10.7745, 106.7130], [10.7550, 106.7150], [10.7500, 106.7000]],
    "Quận 5": [[10.7620, 106.6990], [10.7500, 106.7000], [10.7450, 106.6600], [10.7580, 106.6600]],
    "Quận 6": [[10.7580, 106.6600], [10.7450, 106.6600], [10.7350, 106.6300], [10.7500, 106.6250]],
    "Quận 7": [[10.7550, 106.7150], [10.7400, 106.7400], [10.7100, 106.7500], [10.7150, 106.6950]],
    "Quận 8": [[10.7450, 106.6600], [10.7150, 106.6950], [10.7000, 106.6000], [10.7250, 106.6000]],
    "Quận 10": [[10.7800, 106.6600], [10.7620, 106.6990], [10.7580, 106.6600], [10.7700, 106.6550]],
    "Quận 11": [[10.7700, 106.6550], [10.7580, 106.6600], [10.7500, 106.6250], [10.7650, 106.6350]],
    "Quận 12": [[10.8800, 106.6200], [10.8900, 106.6900], [10.8050, 106.7000], [10.8000, 106.6400]],
    "Bình Thạnh": [[10.8200, 106.7100], [10.8000, 106.7300], [10.7850, 106.7050], [10.7950, 106.6850]],
    "Gò Vấp": [[10.8500, 106.6500], [10.8400, 106.6900], [10.8000, 106.6800], [10.8100, 106.6400]],
    "Phú Nhuận": [[10.8000, 106.6800], [10.7950, 106.6850], [10.7850, 106.6700], [10.7950, 106.6650]],
    "Tân Bình": [[10.8100, 106.6400], [10.8000, 106.6600], [10.7650, 106.6350], [10.7750, 106.6150]],
    "Tân Phú": [[10.8000, 106.6150], [10.7750, 106.6150], [10.7650, 106.6350], [10.7450, 106.6100]],
    "Bình Tân": [[10.8000, 106.6000], [10.7450, 106.6100], [10.6800, 106.6000], [10.7200, 106.5300]]
}

def get_district_name(lat, lng):
    for district_name, polygon in TPHCM_DISTRICTS.items():
        n = len(polygon)
        inside = False
        p1x, p1y = polygon[0]
        for i in range(n + 1):
            p2x, p2y = polygon[i % n]
            if lat > min(p1x, p2x):
                if lat <= max(p1x, p2x):
                    if lng <= max(p1y, p2y):
                        if p1x != p2x:
                            xints = (lat - p1x) * (p2y - p1y) / (p2x - p1x) + p1y
                        if p1y == p2y or lng <= xints:
                            inside = not inside
            p1x, p1y = p2x, p2y
        if inside:
            return district_name
    return None

@app.route('/')
@login_required
def index():
    if current_user.role == 'renter':
        return redirect(url_for('renter_dashboard'))
    users = MotorbikeUser.query.all()
    alert_count = 0
    for user in users:
        user.formatted_time = user.start_time.strftime("%H:%M - %d/%m/%Y")
        district = get_district_name(user.lat, user.lng)
        user.is_safe = (district is not None)
        if not user.is_safe:
            alert_count += 1
    return render_template('index.html', users=users, alert_count=alert_count)


@app.route('/api/update_location', methods=['POST'])
def update_location():
    data = request.get_json()
    user_id     = data.get('user_id')
    new_lat     = data.get('lat')
    new_lng     = data.get('lng')
    new_speed   = data.get('speed', 0.0)
    theft_alert = data.get('theft_alert', False)
    is_fallen   = data.get('is_fallen', False)

    user = MotorbikeUser.query.get(user_id)
    if user:
        user.lat          = new_lat
        user.lng          = new_lng
        user.speed        = new_speed
        user.theft_alert  = theft_alert
        user.is_fallen    = is_fallen
        user.updated_at   = datetime.now()

        current_district = get_district_name(new_lat, new_lng)
        new_history = LocationHistory(
            user_id=user_id,
            lat=new_lat,
            lng=new_lng,
            district=current_district
        )
        db.session.add(new_history)
        db.session.commit()
        return jsonify({"status": "success", "district": current_district})
    return jsonify({"status": "error"}), 404

@app.route('/locate/<int:user_id>')
@login_required
def locate_vehicle(user_id):
    user = MotorbikeUser.query.get_or_404(user_id)
    return render_template('single_map.html', user=user)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register')
@login_required
def register():
    return render_template('register.html')

@app.route('/map_all')
@login_required
def map_all():
    users = MotorbikeUser.query.all()
    if not users:
        flash('Chưa có xe nào được đăng ký!', 'warning')
        return redirect(url_for('index'))
    return render_template('map_all.html', users=users)

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = MotorbikeUser.query.get_or_404(user_id)
    if request.method == 'POST':
        user.name          = request.form.get('name')
        user.phone         = request.form.get('phone')
        user.license_plate = request.form.get('license_plate')
        user.cccd          = request.form.get('cccd')
        if 'profile_img' in request.files:
            file = request.files['profile_img']
            if file and file.filename != '':
                filename  = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                user.profile_img = filename
        db.session.commit()
        flash('Cập nhật thành công!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_user.html', user=user)


@app.route('/api/get_all_locations', methods=['GET'])
def get_all_locations():
    users = MotorbikeUser.query.all()
    user_list = []
    for user in users:
        district    = get_district_name(user.lat, user.lng)
        seconds_ago = (datetime.now() - user.updated_at).total_seconds() if user.updated_at else 9999
        user_list.append({
            'id':            user.id,
            'lat':           user.lat,
            'lng':           user.lng,
            'name':          user.name,
            'license_plate': user.license_plate,
            'phone':         user.phone,
            'cccd':          user.cccd,
            'profile_img':   user.profile_img,
            'district':      district,
            'speed':         user.speed or 0.0,
            'theft_alert':   user.theft_alert or False,
            'is_fallen':     user.is_fallen or False,
            'is_online':     seconds_ago < 15
        })
    response = make_response(jsonify(user_list))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response


@app.route('/api/get_location/<int:user_id>', methods=['GET'])
def get_location(user_id):
    user = MotorbikeUser.query.get(user_id)
    if user:
        district    = get_district_name(user.lat, user.lng)
        seconds_ago = (datetime.now() - user.updated_at).total_seconds() if user.updated_at else 9999
        is_online   = seconds_ago < 15
        data = {
            'lat':           user.lat,
            'lng':           user.lng,
            'name':          user.name,
            'license_plate': user.license_plate,
            'profile_img':   user.profile_img,
            'is_safe':       (district is not None),
            'district':      district,
            'speed':         user.speed or 0.0,
            'theft_alert':   user.theft_alert or False,
            'is_fallen':     user.is_fallen or False,
            'is_online':     is_online,
        }
        response = make_response(jsonify(data))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
    return jsonify({'status': 'error', 'message': 'Không tìm thấy xe'}), 404

@app.route('/api/upload_qr', methods=['POST'])
@login_required
def upload_qr():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file'})
    file      = request.files['file']
    img_array = np.frombuffer(file.read(), np.uint8)
    img       = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is not None:
        gray            = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        decoded_objects = decode(gray)
        if decoded_objects:
            qr_data = decoded_objects[0].data.decode('utf-8')
            parts   = qr_data.split('|')
            if len(parts) >= 3:
                return jsonify({'cccd': parts[0], 'name': parts[2]})
    return jsonify({'status': 'error', 'message': 'QR not found'})

@app.route('/api/app_login', methods=['POST'])
def app_login():
    name = request.form.get('name')
    cccd = request.form.get('cccd')
    user = MotorbikeUser.query.filter_by(name=name, cccd=cccd).first()
    if user:
        return jsonify({'status': 'success', 'user_id': user.id}), 200
    return jsonify({'status': 'error', 'message': 'Thông tin đăng nhập không khớp!'}), 401

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role     = request.form.get('role')
        username = request.form.get('username')
        password = request.form.get('password')
        if role == 'admin':
            if username == 'khanhne' and password == '123':
                user = User('admin_1', role='admin')
                login_user(user)
                return redirect(url_for('index'))
            flash("Sai tài khoản hoặc mật khẩu Admin!", "danger")
        else:
            renter = MotorbikeUser.query.filter_by(name=username, cccd=password).first()
            if renter:
                user = User(renter.id, role='renter')
                login_user(user)
                return redirect(url_for('renter_dashboard'))
            flash("Name or CCCD incorrect!", "danger")
    return render_template('login.html')

@app.route('/history')
@login_required
def history():
    user_data    = MotorbikeUser.query.get(current_user.id)
    history_logs = LocationHistory.query.filter_by(user_id=current_user.id).order_by(LocationHistory.timestamp.desc()).all()
    return render_template('history.html', user=user_data, logs=history_logs)

@app.route('/renter-dashboard')
@login_required
def renter_dashboard():
    user_data = MotorbikeUser.query.get(current_user.id)
    if not user_data:
        return "Không tìm thấy dữ liệu xe!", 404
    return render_template('renter_dashboard.html', user=user_data)

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    file = request.files.get('profile_img')
    if file and file.filename != '':
        filename  = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        new_user = MotorbikeUser(
            license_plate=request.form.get('license_plate'),
            name         =request.form.get('name'),
            cccd         =request.form.get('cccd'),
            phone        =request.form.get('phone'),
            profile_img  =filename,
            lat          =float(request.form.get('lat', 10.7769)),
            lng          =float(request.form.get('lng', 106.7009))
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('index'))
    return "Lỗi: Không có ảnh chân dung!"

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    user = MotorbikeUser.query.get_or_404(user_id)
    try:
        if user.profile_img:
            img_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_img)
            if os.path.exists(img_path):
                os.remove(img_path)
        LocationHistory.query.filter_by(user_id=user_id).delete()
        db.session.delete(user)
        db.session.commit()
        flash(f'Đã xóa thông tin xe {user.license_plate} thành công!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa: {str(e)}', 'danger')
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
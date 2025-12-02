import os
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from Adafruit_IO import Client, errors
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

AIO_USERNAME = os.getenv('AIO_USERNAME')
AIO_KEY = os.getenv('AIO_KEY')
aio = Client(AIO_USERNAME, AIO_KEY)


class EnvData(db.Model):
    __tablename__ = 'env_data'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)


class SecurityData(db.Model):
    __tablename__ = 'security_data'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    motion_count = db.Column(db.Integer, default=0)
    smoke_count = db.Column(db.Integer, default=0)
    sound_count = db.Column(db.Integer, default=0)


def get_live_data(feed_name):
    try:
        data = aio.receive(feed_name)
        return data.value
    except:
        return 'N/A'


def publish_to_feed(feed_name, value):
    try:
        aio.send_data(feed_name, value)
        return True
    except Exception as e:
        app.logger.error(f"Failed to publish to {feed_name}: {e}")
        return False


@app.route('/')
def index():
    live_temp = get_live_data('temperature-feed')
    live_humid = get_live_data('humidity-feed')
    live_pressure = get_live_data('pressure-feed')
    system_mode = get_live_data('system-mode')

    try:
        latest_env = EnvData.query.order_by(EnvData.timestamp.desc()).first()
    except:
        latest_env = None

    try:
        latest_security = SecurityData.query.order_by(SecurityData.timestamp.desc()).first()
    except:
        latest_security = None

    return render_template('index.html',
                           live_temp=live_temp,
                           live_humid=live_humid,
                           live_pressure=live_pressure,
                           system_mode=system_mode,
                           latest_env=latest_env,
                           latest_security=latest_security)


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/environmental')
def environmental():
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('environmental.html', today=today)


@app.route('/security')
def security():
    system_mode = get_live_data('system-mode')
    return render_template('security.html', system_mode=system_mode)


@app.route('/control')
def control():
    light_status = get_live_data('light-control')
    fan_status = get_live_data('fan-control')
    buzzer_status = get_live_data('buzzer-control')

    return render_template('control. html',
                           light_status=light_status,
                           fan_status=fan_status,
                           buzzer_status=buzzer_status)


@app.route('/api/environmental/data', methods=['POST'])
def get_environmental_data():
    data = request.get_json()
    selected_date = data.get('date')
    sensor = data.get('sensor')

    try:
        date_obj = datetime.strptime(selected_date, '%Y-%m-%d')
        start_date = date_obj.replace(hour=0, minute=0, second=0)
        end_date = date_obj.replace(hour=23, minute=59, second=59)

        records = EnvData.query.filter(
            EnvData.timestamp >= start_date,
            EnvData.timestamp <= end_date
        ).order_by(EnvData.timestamp.asc()).all()

        timestamps = [r.timestamp.isoformat() for r in records]

        if sensor == 'temperature':
            values = [r.temperature for r in records]
        elif sensor == 'humidity':
            values = [r.humidity for r in records]
        elif sensor == 'pressure':
            values = [r.pressure for r in records]
        else:
            return jsonify({'error': 'Invalid sensor'}), 400

        return jsonify({
            'timestamps': timestamps,
            'values': values,
            'sensor': sensor
        })
    except Exception as e:
        app.logger.error(f"Error fetching environmental data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/security/data', methods=['POST'])
def get_security_data():
    data = request.get_json()
    selected_date = data.get('date')

    try:
        date_obj = datetime.strptime(selected_date, '%Y-%m-%d')
        start_date = date_obj.replace(hour=0, minute=0, second=0)
        end_date = date_obj.replace(hour=23, minute=59, second=59)

        records = SecurityData.query.filter(
            SecurityData.timestamp >= start_date,
            SecurityData.timestamp <= end_date
        ).order_by(SecurityData.timestamp.desc()).all()

        intrusions = []
        for r in records:
            if r.motion_count > 0 or r.smoke_count > 0 or r.sound_count > 0:
                intrusions.append({
                    'timestamp': r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'motion_count': r.motion_count,
                    'smoke_count': r.smoke_count,
                    'sound_count': r.sound_count
                })

        return jsonify({'intrusions': intrusions})
    except Exception as e:
        app.logger.error(f"Error fetching security data: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/control/<device>', methods=['POST'])
def control_device(device):
    data = request.get_json()
    command = data.get('command')

    feed_map = {
        'light': 'light-control',
        'fan': 'fan-control',
        'buzzer': 'buzzer-control'
    }

    if device in feed_map:
        success = publish_to_feed(feed_map[device], command)
        return jsonify({'success': success, 'device': device, 'command': command})

    return jsonify({'success': False, 'error': 'Invalid device'}), 400


@app.route('/api/security/mode', methods=['POST'])
def set_security_mode():
    data = request.get_json()
    mode = data.get('mode')

    if mode in ['Home', 'Away']:
        success = publish_to_feed('system-mode', mode)
        return jsonify({'success': success, 'mode': mode})

    return jsonify({'success': False, 'error': 'Invalid mode'}), 400


@app.route('/api/camera/trigger', methods=['POST'])
def trigger_camera():
    success = publish_to_feed('camera-trigger', 'TAKE_PHOTO')
    return jsonify({'success': success})


@app.route('/create_db')
def create_db():
    try:
        with app.app_context():
            db.create_all()
        return "Database tables created successfully!"
    except Exception as e:
        return f"Error creating tables: {str(e)}", 500


if __name__ == '__main__':
    app.run(debug=True)
import os
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from Adafruit_IO import Client, errors
from datetime import datetime, timedelta

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os. getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

AIO_USERNAME = os.getenv('AIO_USERNAME')
AIO_KEY = os.getenv('AIO_KEY')
aio = Client(AIO_USERNAME, AIO_KEY)


class EnvData(db.Model):
    __tablename__ = 'env_data'
    id = db. Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)


def get_live_data(feed_name):
    try:
        data = aio.receive(feed_name)
        return data. value
    except errors.RequestError:
        return 'N/A'
    except errors.AdafruitIOError:
        return 'N/A'
    except Exception:
        return 'N/A'


def publish_to_feed(feed_name, value):
    try:
        aio.send_data(feed_name, value)
        return True
    except errors.AdafruitIOError as e:
        app.logger.error(f"Failed to publish to {feed_name}: {e}")
        return False


@app.route('/')
def index():
    live_temp = get_live_data('temperature-feed')
    live_humid = get_live_data('humidity-feed')
    live_pressure = get_live_data('pressure-feed')

    light_status = get_live_data('light-control')
    fan_status = get_live_data('fan-control')
    buzzer_status = get_live_data('buzzer-control')
    system_mode = get_live_data('system-mode')

    recent_env = EnvData.query.order_by(EnvData.timestamp.desc()).limit(10).all()

    return render_template('index.html',
                           live_temp=live_temp,
                           live_humid=live_humid,
                           live_pressure=live_pressure,
                           light_status=light_status,
                           fan_status=fan_status,
                           buzzer_status=buzzer_status,
                           system_mode=system_mode,
                           recent_env=recent_env)


@app. route('/api/control/<device>', methods=['POST'])
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


@app.route('/api/mode', methods=['POST'])
def set_mode():
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


@app.route('/api/chart/environmental')
def chart_environmental():
    hours = request.args.get('hours', 24, type=int)
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    data = EnvData.query.filter(EnvData.timestamp >= cutoff).order_by(EnvData.timestamp.asc()).all()

    return jsonify({
        'timestamps': [d.timestamp. isoformat() for d in data],
        'temperature': [d.temperature for d in data],
        'humidity': [d.humidity for d in data],
        'pressure': [d.pressure for d in data]
    })


@app.route('/create_db')
def create_db():
    with app.app_context():
        db.create_all()
    return "Database tables created!"


if __name__ == '__main__':
    app.run(debug=True)
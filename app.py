import os
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from Adafruit_IO import Client, errors

load_dotenv()

app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Adafruit IO Credentials (fetched from .env or Render's env vars)
AIO_USERNAME = os.getenv('AIO_USERNAME')
AIO_KEY = os.getenv('AIO_KEY')
aio = Client(AIO_USERNAME, AIO_KEY)


# --- Database Model (for Historical Data) ---
class SensorData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    feed_name = db.Column(db.String(80), nullable=False)
    value = db.Column(db.String(120), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=db.func.now())

    def __repr__(self):
        return f'<SensorData {self.feed_name}: {self.value}>'


# --- Helper Function for Adafruit IO (Live Data) ---
def get_live_data(feed_name):
    try:
        data = aio.receive(feed_name)
        return data.value
    except errors.AdafruitIOError:
        return 'N/A'


# --- Routes ---
@app.route('/')
def index():
    # Fetch live data from Adafruit IO
    live_temp = get_live_data('temperature-feed')
    live_humid = get_live_data('humidity-feed')

    # Fetch historical data from Postgres DB (e.g., last 10 entries)
    historical_data = SensorData.query.order_by(SensorData.timestamp.desc()).limit(10).all()

    return render_template('index.html', live_temp=live_temp, live_humid=live_humid, historical_data=historical_data)


@app.route('/create_db')
def create_db():
    with app.app_context():
        db.create_all()
    return "Database tables created!"


# --- Main Run Block for Local Development ---
if __name__ == '__main__':
    app.run(debug=True)
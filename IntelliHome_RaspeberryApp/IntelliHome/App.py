import json
import time
import threading
import os
import logging
from datetime import datetime
from pathlib import Path

from MQTT_communicator import MQTT_communicator
from environmental_module import environmental_module
from security_module import security_module
from device_control_module import device_control_module
from db_manager import DB_Manager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging. getLogger(__name__)

ENV_FEEDS = {
    "temperature": "temperature-feed",
    "humidity": "humidity-feed",
    "pressure": "pressure-feed"
}
SECURITY_FEEDS = {
    "motion_count": "motion-feed",
    "smoke_count": "smoke-feed",
    "sound_count": "sound-feed"
}
CONTROL_FEEDS = {
    "light": "light-control",
    "fan": "fan-control",
    "buzzer": "buzzer-control",
    "mode": "system-mode",
    "camera": "camera-trigger"
}

class DomiSafeApp:
    def __init__(self, config_file='config.json'):
        self. config = self.load_config(config_file)
        self. running = True
        self.system_mode = 'Home'
        
        self.security_check_interval = self.config.get('security_check_interval', 5)
        self.security_send_interval = self.config.get('security_send_interval', 60)
        self.env_interval = self.config.get('env_interval', 360)
        self.flushing_interval = self.config. get('flushing_interval', 10)

        self.mqtt_agent = MQTT_communicator(config_file)
        self.env_data = environmental_module(config_file)
        self.security_data = security_module(config_file)
        self.device_control = device_control_module(config_file)
        self.db_manager = DB_Manager(config_file)
        
        self.setup_control_subscribers()

    def load_config(self, config_file):
        default_config = {
             "security_check_interval": 5, "security_send_interval": 60,
             "env_interval": 360, "flushing_interval": 10,
             "cooldown_duration_sec": 10
        }
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                return {**default_config, **config}
        except FileNotFoundError:
            logger.warning(f"Config file {config_file} not found, using defaults")
            return default_config

    def setup_control_subscribers(self):
        self.mqtt_agent.set_command_handler(self.handle_incoming_mqtt_command)
        feeds_to_subscribe = list(CONTROL_FEEDS.values())
        self.mqtt_agent.subscribe_to_feeds(feeds_to_subscribe)
        logger.info(f"Subscribed to control feeds: {feeds_to_subscribe}")

    def handle_incoming_mqtt_command(self, feed_name, payload):
        if feed_name == CONTROL_FEEDS['mode']:
            self.set_system_mode(payload)
            return

        if feed_name == CONTROL_FEEDS['camera'] and payload. upper() in ('TAKE_PHOTO', '1'):
             logger.critical("📸 Remote Photo Triggered by Dashboard Command.")
             self.security_data.trigger_manual_capture()
             self.mqtt_agent.send_to_adafruit_io(CONTROL_FEEDS['camera'], "PHOTO_TAKEN")
             return
        
        for device_name, feed_key in CONTROL_FEEDS.items():
            if feed_name == feed_key and device_name not in ('mode', 'camera'):
                self.device_control.process_command(device_name, payload)
                break
                
    def set_system_mode(self, new_mode_raw):
        new_mode = str(new_mode_raw).strip(). title()
        if new_mode in ['Home', 'Away']: 
            self.system_mode = new_mode
            logger.critical(f"🚀 SYSTEM MODE UPDATED TO: {self.system_mode}")
        else:
            logger.warning(f"Invalid mode received: {new_mode_raw}. Mode remains {self.system_mode}")

    def send_to_cloud(self, data, feeds):
        success = True
        for sensor_name, feed_key in feeds.items():
            if sensor_name in data:
                if not self.mqtt_agent.send_to_adafruit_io(feed_key, data[sensor_name]):
                    success = False
                time.sleep(0.5)
        return success
        
    def collect_environmental_data(self, current_time, timers, file_handle):
        if current_time - timers['env_check'] >= self.env_interval:
            env_data = self.env_data.get_environmental_data()
            
            file_handle.write(json.dumps(env_data) + "\n")
            file_handle. flush()
            
            self.db_manager.insert_env_data(env_data)
            logger.info(f"📊 Environmental Data: Temp={env_data['temperature']}°C, Humidity={env_data['humidity']}%, Pressure={env_data['pressure']}hPa")

            if self.send_to_cloud(data=env_data, feeds=ENV_FEEDS):
                logger.info("✅ Environmental data sent to cloud (MQTT)")
            else:
                logger.warning("❌ Offline, env data saved locally.  Will sync later.")
                
            timers['env_check'] = current_time

    def collect_security_data(self, current_time, timers, security_counts, file_handle):
        if current_time - timers['security_check'] >= self.security_check_interval:
            sec_data = self.security_data.get_security_data()
            
            for key in ['motion', 'smoke', 'sound']:
                if sec_data. get(f'{key}_detected', False): 
                    security_counts[key] += 1
                    logger.warning(f"🚨 INTRUSION DETECTED: {key. upper()} - Count: {security_counts[key]}")
            
            if any(sec_data.get(f'{key}_detected', False) for key in ['motion', 'smoke', 'sound']):
                file_handle.write(json.dumps(sec_data) + "\n")
                file_handle.flush()
            
            timers['security_check'] = current_time

        if current_time - timers['security_send'] >= self.security_send_interval:
            if security_counts['motion'] > 0 or security_counts['smoke'] > 0 or security_counts['sound'] > 0:
                security_summary = {
                    'timestamp': datetime.utcnow().isoformat(),
                    'motion_count': security_counts['motion'],
                    'smoke_count': security_counts['smoke'],
                    'sound_count': security_counts['sound']
                }
                
                self.db_manager.insert_security_summary(security_summary)
                logger.critical(f"🚨 Security Summary: Motion={security_counts['motion']}, Smoke={security_counts['smoke']}, Sound={security_counts['sound']}")
                
                if self.send_to_cloud(data=security_summary, feeds=SECURITY_FEEDS):
                    logger.info("✅ Security summary sent to cloud (MQTT)")
                else:
                    logger.warning("❌ Failed to send security summary (offline).  Saved locally.")
                    
                security_counts['motion'] = 0
                security_counts['smoke'] = 0
                security_counts['sound'] = 0
            else:
                logger.debug("No security events to report this interval")
                
            timers['security_send'] = current_time

    def data_collection_loop(self):
        timestamp = datetime.now().strftime("%Y%m%d")
        
        environmental_data_filename = f"logs/{timestamp}_environmental_data.txt"
        security_data_filename = f"logs/{timestamp}_security_data.txt"
        device_status_filename = f"logs/{timestamp}_device_status.txt"
        
        Path("logs").mkdir(exist_ok=True)
        
        with open(environmental_data_filename, "a", buffering=1) as file1, \
             open(security_data_filename, "a", buffering=1) as file2, \
             open(device_status_filename, "a", buffering=1) as file3:
            
            logger.info(f"Logging to files starting with {timestamp}_...")
            last_fsync = time.time()
            timers = {'env_check': 0, 'security_check': 0, 'security_send': time.time()}
            security_counts = {'motion': 0, 'smoke': 0, 'sound': 0}
            
            while self.running:
                try:
                    current_time = time.time()
                    
                    self.collect_environmental_data(current_time, timers, file1)
                    
                    if self.system_mode == 'Away':
                        self.collect_security_data(current_time, timers, security_counts, file2)
                    
                    if current_time - last_fsync > self.flushing_interval:
                        for fh in (file1, file2, file3):
                            fh.flush()
                            os.fsync(fh.fileno())
                        last_fsync = current_time
                        
                    time.sleep(self.security_check_interval)
                    
                except Exception as e:
                    logger.error(f"Error in data collection loop: {e}", exc_info=True)
                    time.sleep(5)
                    
    def db_sync_loop(self):
        SYNC_INTERVAL_SEC = 30
        while self.running:
            try:
                time.sleep(5)
                if self.mqtt_agent.is_connected(): 
                    synced_count = self.db_manager.synchronize_to_cloud()
                    if synced_count > 0:
                        logger.critical(f"☁️ Successfully synced {synced_count} records to cloud DB.")
                else:
                    logger.debug("Offline.  Skipping cloud sync.  Data saved locally.")
            except Exception as e:
                logger.error(f"Error during DB sync: {e}", exc_info=True)
            
            time.sleep(SYNC_INTERVAL_SEC)
                    
    def start(self):
        self.running = True
        logger.info("Starting DomiSafe IoT System")
        
        data_thread = threading.Thread(target=self.data_collection_loop)
        data_thread.start()
        
        sync_thread = threading.Thread(target=self.db_sync_loop, daemon=True)
        sync_thread.start()
        
        try:
            while self.running:
                time. sleep(1)
        except KeyboardInterrupt:
            logger. info("👋 Shutting down application...")
        finally:
            self.running = False
            data_thread.join(timeout=10)
            sync_thread.join(timeout=10)
            
            try:
                if hasattr(self. security_data, 'picam2') and callable(getattr(self.security_data. picam2, 'stop', None)):
                    self.security_data.picam2.stop() 
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
                
            logger.info("Stopped.")


if __name__ == "__main__":
    app = DomiSafeApp(config_file='./config.json') 
    app.start()

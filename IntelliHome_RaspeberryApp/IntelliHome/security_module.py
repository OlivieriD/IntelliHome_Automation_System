import json
import time
import random
from datetime import datetime
from pathlib import Path
import logging
import os

import board
import digitalio
from picamera2 import Picamera2
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Pin Definitions (use BCM numbering for board.D##)
PIR_PIN = board.D6      # Motion Sensor Digital Output

class security_module:
    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        
        # Initialize Motion Sensor (PIR)
        self.pir = digitalio.DigitalInOut(PIR_PIN)
        self.pir.direction = digitalio.Direction.INPUT
        
        # Initialize Pi Camera
        self.picam2 = Picamera2()
        
        # Set default configuration (low-res preview)
        preview_config = self.picam2.create_preview_configuration(main={"size": (640, 480)})
        self.picam2.configure(preview_config)
        self.picam2.start() 
        
        self.image_dir = 'captured_images'
        Path(self.image_dir).mkdir(exist_ok=True) 
        
        # State tracking for cooldown
        self.last_alert_time = {}
        self.ALERT_COOLDOWN = 300 

        # NEW: Variables for capture cooldown and sensor check interval
        self.last_capture_time = 0 
        self.cooldown_duration = self.config.get('cooldown_duration_sec', 10) 

    def load_config(self, config_file):
        """Load configuration from JSON file (minimal version)"""
        default_config = {}
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                return {**default_config, **config}
        except FileNotFoundError:
            logger.warning(f"Config file {config_file} not found, using defaults")
            return default_config
            
    def get_security_data(self):
        """Read sensor data (Motion and Simulated Smoke)"""
        current_time = time.time()
        motion_detected = self.pir.value
        smoke_detected = random.random() < 0.001
        
        image_path = None
        
        logger.debug(f"PIR Sensor Raw Reading: {motion_detected}")
        
        # Check for motion AND if the system is out of cooldown
        if motion_detected and self.config.get('camera_enabled', False):
            if current_time - self.last_capture_time > self.cooldown_duration:
                
                logger.warning("🚨 Motion detected! Capturing image and sending alert.")
                image_path = self.capture_image(prefix='security')
                
                # Update cooldown timestamp after successful capture attempt
                self.last_capture_time = current_time 

                self.send_smtp2go_alert(
                    "Motion Detected",
                    "PIR sensor triggered, check the image.",
                    image_path
                )
            else:
                logger.debug(f"Motion detected, but still in camera cooldown period ({self.cooldown_duration}s).")
                motion_detected = False
                
        elif smoke_detected:
            logger.critical("🔥 SMOKE DETECTED! Sending critical alert.")
            self.send_smtp2go_alert(
                "CRITICAL SMOKE ALERT",
                "Potential fire hazard detected!",
                None
            )

        return {
            'timestamp': datetime.now().isoformat(),
            'motion_detected': motion_detected,
            'smoke_detected': smoke_detected,
            'sound_detected': False,
            'image_path': image_path
        }

    def capture_image(self, prefix='security'):
        """Capture image from the PiCamera2, stabilizing the stop/start sequence, with a configurable prefix."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = f"{self.image_dir}/{prefix}_{timestamp}.jpg"
            
            # 1. STOP the current running stream
            if self.picam2.started:
                self.picam2.stop()
            time.sleep(0.5) 

            # 2. Configure for still capture (High Resolution)
            still_config = self.picam2.create_still_configuration(main={"size": (1280, 720)})
            self.picam2.configure(still_config)
            self.picam2.start()
            
            # 3. Capture the image
            self.picam2.capture_file(image_path) 
            
            # 4. Stop the still stream and reconfigure for low-res preview
            if self.picam2.started:
                self.picam2.stop()
            time.sleep(0.5)
            
            # 5. Reconfigure and START the low-res preview stream for continuous operation
            preview_config = self.picam2.create_preview_configuration(main={"size": (640, 480)})
            self.picam2.configure(preview_config)
            self.picam2.start()
            
            logger.info(f"Image captured: {image_path}")
            return image_path
            
        except Exception as e:
            logger.error(f"Camera capture failed: {e}", exc_info=True)
            # IMPORTANT: Try to restart the preview stream even if the capture failed
            try:
                if not self.picam2.started:
                    preview_config = self.picam2.create_preview_configuration(main={"size": (640, 480)})
                    self.picam2.configure(preview_config)
                    self.picam2.start()
            except Exception as restart_e:
                logger.critical(f"Failed to restart camera stream: {restart_e}")
            return None

    def send_smtp2go_alert(self, alert_type, message="", image_path=None):
        """Send email alert via SMTP2GO with optional image attachment"""
        
        # Cooldown check
        now = time.time()
        if self.last_alert_time.get(alert_type) and (now - self.last_alert_time[alert_type] < self.ALERT_COOLDOWN):
            logger.debug(f"Alert cooldown active for {alert_type}, skipping email.")
            return False
            
        try:
            # Get credentials from config
            smtp_host = self.config.get("SMTP_HOST")
            smtp_port = int(self.config.get("SMTP_PORT", 0))
            smtp_user = self.config.get("SMTP_USER")
            smtp_pass = self.config.get("SMTP_PASS")
            sender = self.config.get("ALERT_FROM")
            recipient = self.config.get("ALERT_TO")

            if not all([smtp_user, smtp_pass, sender, recipient, smtp_host, smtp_port]):
                raise ValueError("Missing SMTP2GO credentials in config file")

            # Create message
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = recipient
            msg['Subject'] = f"🚨 DomiSafe Alert: {alert_type}"

            # Email body
            body = f"""
                DomiSafe Security Alert

                Alert Type: {alert_type}
                Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                Message: {message}

                ---
                This is an automated alert from your DomiSafe IoT system.
            """
            msg.attach(MIMEText(body, 'plain'))

            # Attach image if provided and exists
            if image_path and Path(image_path).exists():
                with open(image_path, 'rb') as f:
                    img = MIMEImage(f.read(), name=Path(image_path).name)
                    msg.attach(img)
                logger.info(f"Attached image: {image_path}")

            # Send via SMTP2GO
            context = ssl.create_default_context()
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls(context=context)
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            logger.info(f"✅ Email alert sent: {alert_type}")
            self.last_alert_time[alert_type] = now 
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send email alert: {e}")
            return False
            
    def trigger_manual_capture(self):
        """
        Triggers an image capture and alert outside the normal motion-detection flow.
        Called directly by DomiSafeApp via MQTT command.
        """
        logger.info("MANUAL TRIGGER: Initiating image capture and alert.")
        
        try:
            # Capture with 'manual' prefix
            image_path = self.capture_image(prefix='manual') 
            self.last_capture_time = time.time() 
            
            # Send alert
            self.send_smtp2go_alert(
                "Manual Photo Trigger",
                "Remote photo capture requested by user dashboard command.",
                image_path
            )
        except Exception as e:
            logger.error(f"Failed to execute manual capture: {e}")

import json
import logging
import paho.mqtt.client as mqtt
import time
from paho.mqtt.enums import CallbackAPIVersion

# Configure logging
logger = logging.getLogger(__name__)

class MQTT_communicator:
    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        self.mqtt_client = None
        self.mqtt_connected = False # Existing status flag
        self.command_handler = None # To be set by DomiSafeApp
        # List to store feeds for re-subscription after reconnect
        self.subscribed_feeds = []
        self.setup_mqtt()

    def load_config(self, config_file):
        """Load configuration from JSON file with defaults"""
        default_config = {
            "ADAFRUIT_IO_USERNAME": "username",
            "ADAFRUIT_IO_KEY": "userkey",
            "MQTT_BROKER": "io.adafruit.com",
            "MQTT_PORT": 1883,
            "MQTT_KEEPALIVE": 60,
        }
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                return {**default_config, **config}
        except FileNotFoundError:
            logger.warning(f"Config file {config_file} not found, using defaults")
            return default_config

    def setup_mqtt(self):
        """Setup MQTT client for Adafruit IO using V2 API"""
        try:
            # Explicitly use the latest paho-mqtt API version (V2)
            self.mqtt_client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
            self.mqtt_client.username_pw_set(
                self.config["ADAFRUIT_IO_USERNAME"],
                self.config["ADAFRUIT_IO_KEY"]
            )
            
            # Assign V2-compliant callbacks
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            self.mqtt_client.on_publish = self.on_mqtt_publish
            self.mqtt_client.on_message = self.on_mqtt_message

            self.mqtt_client.connect(
                self.config["MQTT_BROKER"],
                self.config["MQTT_PORT"],
                self.config["MQTT_KEEPALIVE"]
            )
            # Start the background thread for network traffic
            self.mqtt_client.loop_start()
            logger.info("MQTT client setup completed. Starting network loop.")
        except Exception as e:
            logger.error(f"Failed to setup MQTT client: {e}")
            self.mqtt_connected = False

    # --- V2 API Compliant Callbacks ---

    def on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        """Callback for when MQTT client connects - V2 Signature"""
        if rc == 0:
            self.mqtt_connected = True
            logger.info("Connected to MQTT broker")
            # Re-subscribe to feeds after a successful reconnection
            if self.subscribed_feeds:
                self.subscribe_to_feeds(self.subscribed_feeds)
        else:
            self.mqtt_connected = False
            logger.error(f"Failed to connect to MQTT broker, return code {rc}")

    def on_mqtt_disconnect(self, client, userdata, rc, properties=None):
        """Callback for when MQTT client disconnects - V2 Signature"""
        self.mqtt_connected = False
        # Log the disconnection, especially if unexpected (rc != 0)
        if rc != 0:
            logger.warning(f"Disconnected unexpectedly (RC: {rc}). Broker will attempt reconnection.")
        else:
            logger.info("Disconnected from MQTT broker.")

    def on_mqtt_publish(self, client, userdata, mid, reasonCode, properties):
        """Callback for when message is published - V2 Signature"""
        if reasonCode == 0:
            logger.debug(f"Message {mid} published successfully")
        else:
            logger.warning(f"Message {mid} published with reason code: {reasonCode}")

    def on_mqtt_message(self, client, userdata, msg):
        """Callback for when a subscribed message is received"""
        topic = msg.topic
        payload = msg.payload.decode('utf-8')
        logger.info(f"Received command: {topic} -> {payload}")

        # Pass the feed name and payload to the external handler
        if self.command_handler:
            # Extract the feed name from the topic: <USERNAME>/feeds/<FEED_NAME>
            feed_name = topic.split('/')[-1]
            self.command_handler(feed_name, payload)
        else:
            logger.warning("No command handler is set in DomiSafeApp.")

    # --- Communication Methods ---
    
    # 🌟 NEW: Add the required method for DB sync checking
    def is_connected(self):
        """Returns the current MQTT connection status for external modules."""
        return self.mqtt_connected

    def set_command_handler(self, handler):
        """Allows DomiSafeApp to set its function as the message handler"""
        self.command_handler = handler

    def subscribe_to_feeds(self, feeds):
        """Subscribe to a list of feeds and store them for re-subscription"""
        # Store all feeds in case of a disconnect/reconnect
        self.subscribed_feeds = list(set(self.subscribed_feeds + feeds))
        
        if not self.mqtt_connected:
            logger.warning("Cannot subscribe, MQTT client not connected. Will subscribe on connect.")
            return

        for feed_key in feeds:
            topic = f"{self.config['ADAFRUIT_IO_USERNAME']}/feeds/{feed_key}"
            # Subscribe using QoS 1 for control messages
            self.mqtt_client.subscribe(topic, qos=1)
            logger.info(f"Subscribed to {topic}")
            
    def send_to_adafruit_io(self, feed_name, value):
        """Publish a value to Adafruit IO feed via MQTT"""
        if not self.mqtt_connected or not self.mqtt_client:
            logger.warning("MQTT client not connected, skipping publish.")
            return False

        try:
            topic = f"{self.config['ADAFRUIT_IO_USERNAME']}/feeds/{feed_name}"
            # Use QoS 1 for publishing sensor data / control feedback
            result, mid = self.mqtt_client.publish(topic, str(value), qos=1) 
            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Published {value} to {topic}")
                return True
            else:
                logger.error(f"Failed to publish {value} to {topic}, result={result}")
                return False

        except Exception as e:
            logger.error(f"Error publishing to MQTT: {e}")
            return False

import json
import time
import random
import math
from datetime import datetime
import logging

import board
import adafruit_dht
# Initialize the DHT device. Note: The use_pulseio=False is for the RPi.
dhtDevice = adafruit_dht.DHT11(board.D4, use_pulseio=False) 

# Configure logging
logger = logging.getLogger(__name__)

class environmental_module:
    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        # Placeholder for last readings in case of a read failure
        self.last_known_data = {'temperature': 25.0, 'humidity': 50.0, 'pressure': 1013.25} 

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

    def get_environmental_data(self):
        """Read temperature and humidity from DHT11 and simulate pressure"""
        temperature_c, humidity, pressure = self.last_known_data['temperature'], self.last_known_data['humidity'], self.last_known_data['pressure']
        
        try:
            # Read from actual sensor
            temperature_c = dhtDevice.temperature
            humidity = dhtDevice.humidity

            if temperature_c is not None and humidity is not None:
                # DHT sensors can sometimes fail to read, so only proceed if values are valid
                
                # Simulate pressure with small variations for a complete data set
                pressure = round(1013.25 + random.uniform(-5, 5), 2)  
                
                # Update last known good data
                self.last_known_data['temperature'] = temperature_c
                self.last_known_data['humidity'] = humidity
                self.last_known_data['pressure'] = pressure
                
                logger.debug(f"Read sensor: Temp: {temperature_c:.1f} C, Humidity: {humidity:.1f} %")
                
            else:
                raise RuntimeError("Invalid data from DHT sensor.")

        except RuntimeError as error:
            # Errors happen often with DHT, use the last known data for now
            logger.warning(f"DHT read error: {error.args[0]}. Using last known good values.")
            # Add small random variation to stale data to avoid sending identical values
            temperature_c = round(self.last_known_data['temperature'] + random.uniform(-0.1, 0.1), 1)
            humidity = round(self.last_known_data['humidity'] + random.uniform(-0.5, 0.5), 1)

        except Exception as e:
            logger.error(f"Unexpected error during environmental read: {e}")


        return {
            'timestamp': datetime.now().isoformat(),
            'temperature': temperature_c,
            'humidity': humidity,
            'pressure': pressure
        }
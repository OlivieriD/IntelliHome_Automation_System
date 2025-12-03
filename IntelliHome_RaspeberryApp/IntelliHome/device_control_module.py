import json
from datetime import datetime
import logging

import board
import digitalio

# Configure logging
logger = logging.getLogger(__name__)

# Pin Definitions (Use BCM pin numbers for board.D##)
LIGHT_PIN = board.D21  
FAN_PIN = board.D20    
BUZZER_PIN = board.D18  # Buzzer moved to a dedicated, controlled pin

class device_control_module:
    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        self.devices = {}
        self.initialize_gpios()

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
            
    def initialize_gpios(self):
        """Setup GPIO pins for relays and set initial state (OFF)"""
        
        # List of all controlled devices
        controlled_devices = [("light", LIGHT_PIN), ("fan", FAN_PIN), ("buzzer", BUZZER_PIN)]
        
        for device_name, pin in controlled_devices:
            try:
                self.devices[device_name] = {
                    'pin': digitalio.DigitalInOut(pin),
                    'status': 'off'
                }
                self.devices[device_name]['pin'].direction = digitalio.Direction.OUTPUT
                
                # FIX: Set initial state to OFF using Active-High logic: False=LOW=OFF
                self.devices[device_name]['pin'].value = False  
                logger.info(f"Device {device_name} initialized on pin {pin}. Initial state: OFF")
            except Exception as e:
                logger.error(f"Failed to initialize GPIO for {device_name}: {e}")

    def process_command(self, device_name, command):
        """Execute the command (ON/OFF) for a specified device"""
        if device_name not in self.devices:
            logger.warning(f"Unknown device command: {device_name}")
            return False

        current_pin = self.devices[device_name]['pin']
        cmd = str(command).lower()
        
        # FIX: Implement Active-High logic (HIGH=ON, LOW=OFF)
        if cmd in ('on', '1'):
            current_pin.value = True   # Set HIGH to turn ON 
            self.devices[device_name]['status'] = 'on'
            logger.info(f"Actuator {device_name} turned ON.")
        elif cmd in ('off', '0'):
            current_pin.value = False  # Set LOW to turn OFF 
            self.devices[device_name]['status'] = 'off'
            logger.info(f"Actuator {device_name} turned OFF.")
        else:
            logger.warning(f"Invalid command for {device_name}: {command}")
            return False

        return True

    def get_device_status(self):
        """Return the current status of all controlled devices as a list"""
        device_data = []
        for device_name, dev_info in self.devices.items():
             device_data.append({
                'timestamp': datetime.now().isoformat(),
                'device_name': device_name,
                'status': dev_info['status']
            })
        return device_data

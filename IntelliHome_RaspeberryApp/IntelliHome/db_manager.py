import json
import sqlite3
import logging
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_batch

logger = logging.getLogger(__name__)

class DB_Manager:
    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        self.local_db_path = self.config. get('LOCAL_DB_PATH', 'domisafe_local.db')
        self.cloud_db_url = self.config.get('NEON_DATABASE_URL')
        self.init_local_db()

    def load_config(self, config_file):
        try:
            with open(config_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file {config_file} not found")
            return {}

    def init_local_db(self):
        try:
            conn = sqlite3. connect(self.local_db_path)
            cursor = conn. cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS env_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    humidity REAL NOT NULL,
                    pressure REAL NOT NULL,
                    synced INTEGER DEFAULT 0
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS security_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    motion_count INTEGER DEFAULT 0,
                    smoke_count INTEGER DEFAULT 0,
                    sound_count INTEGER DEFAULT 0,
                    synced INTEGER DEFAULT 0
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info("Local database initialized with synced column")
        except Exception as e:
            logger.error(f"Failed to initialize local database: {e}")

    def insert_env_data(self, data):
        try:
            conn = sqlite3.connect(self. local_db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO env_data (timestamp, temperature, humidity, pressure, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (data['timestamp'], data['temperature'], data['humidity'], data['pressure']))
            conn.commit()
            conn.close()
            logger.info("Environmental data inserted into local DB")
        except Exception as e:
            logger.error(f"Failed to insert env data: {e}")

    def insert_security_summary(self, data):
        try:
            conn = sqlite3. connect(self.local_db_path)
            cursor = conn. cursor()
            cursor.execute('''
                INSERT INTO security_data (timestamp, motion_count, smoke_count, sound_count, synced)
                VALUES (?, ?, ?, ?, 0)
            ''', (data['timestamp'], data['motion_count'], data['smoke_count'], data['sound_count']))
            conn.commit()
            conn.close()
            logger.info(f"Security summary inserted: M:{data['motion_count']}, S:{data['smoke_count']}, A:{data['sound_count']}")
        except Exception as e:
            logger.error(f"Failed to insert security data: {e}")

    def synchronize_to_cloud(self):
        synced_count = 0
        try:
            local_conn = sqlite3.connect(self. local_db_path)
            local_cursor = local_conn.cursor()
            
            cloud_conn = psycopg2.connect(self.cloud_db_url)
            cloud_cursor = cloud_conn.cursor()
            
            local_cursor.execute('SELECT id, timestamp, temperature, humidity, pressure FROM env_data WHERE synced = 0')
            env_records = local_cursor.fetchall()
            
            if env_records:
                execute_batch(cloud_cursor, '''
                    INSERT INTO env_data (timestamp, temperature, humidity, pressure)
                    VALUES (%s, %s, %s, %s)
                ''', [(r[1], r[2], r[3], r[4]) for r in env_records])
                
                env_ids = [r[0] for r in env_records]
                placeholders = ','.join('?' * len(env_ids))
                local_cursor.execute(f'UPDATE env_data SET synced = 1 WHERE id IN ({placeholders})', env_ids)
                synced_count += len(env_records)
                logger.info(f"Synced {len(env_records)} environmental records to cloud")
            
            local_cursor.execute('SELECT id, timestamp, motion_count, smoke_count, sound_count FROM security_data WHERE synced = 0')
            security_records = local_cursor. fetchall()
            
            if security_records:
                execute_batch(cloud_cursor, '''
                    INSERT INTO security_data (timestamp, motion_count, smoke_count, sound_count)
                    VALUES (%s, %s, %s, %s)
                ''', [(r[1], r[2], r[3], r[4]) for r in security_records])
                
                security_ids = [r[0] for r in security_records]
                placeholders = ','.join('?' * len(security_ids))
                local_cursor.execute(f'UPDATE security_data SET synced = 1 WHERE id IN ({placeholders})', security_ids)
                synced_count += len(security_records)
                logger.info(f"Synced {len(security_records)} security records to cloud")
            
            cloud_conn.commit()
            local_conn.commit()
            
            cloud_cursor.close()
            cloud_conn.close()
            local_cursor.close()
            local_conn.close()
            
        except Exception as e:
            logger.error(f"Cloud sync failed: {e}")
        
        return synced_count

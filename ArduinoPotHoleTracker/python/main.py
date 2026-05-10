import json
import requests
import base64
import random
import sqlite3
import time  
import threading 
from datetime import datetime, UTC
from arduino.app_utils import App, Bridge
from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_bricks.web_ui import WebUI

API_ENDPOINT = "http://vlb-cd06317a-3468-4e5b-b751-5429ce5ca5ba.vultrlb.com/road-incidents"
DB_FILE = "viatges.db"

is_moving = False 
current_potholes = 0
update_leds = False

detection_stream = VideoObjectDetection(confidence=0.5, debounce_sec=0.0, camera_preview=True)
ui = WebUI()
ui.on_message("override_th", lambda sid, threshold: detection_stream.override_threshold(threshold))

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT,
            confidence REAL,
            timestamp TEXT,
            lat REAL,
            lng REAL,
            image_base64 TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_to_db(entry):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO detections (label, confidence, timestamp, lat, lng, image_base64)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        entry["label"], entry["confidence"], entry["timestamp"], 
        entry["lat"], entry["lng"], entry["img_b64"]
    ))
    conn.commit()
    conn.close()

def set_moving():
    global is_moving
    is_moving = True
    print("🟢 Bici en moviment. Càmera ACTIVA.")

def set_stopped():
    global is_moving
    is_moving = False
    print("🔴 Bici aturada. Càmera PAUSADA.")

def read_arduino_sensors():
    return {
        "latitude": round(41.3851 + random.uniform(-0.005, 0.005), 6), 
        "longitude": round(2.1734 + random.uniform(-0.005, 0.005), 6)
    }

def get_potholes_num():
    global current_potholes
    return current_potholes

def get_do_leds_potholes():
    global update_leds
    estat_actual = update_leds
    if update_leds:
        update_leds = False 
    return estat_actual

def process_detections(detections: dict, frame_jpeg=None):
    global is_moving, current_potholes, update_leds
    
    if not is_moving:
        return 
        
    potholes_ahora = len(detections.get("pothole", []))
    criticals_ahora = len(detections.get("critical", []))
    
    if potholes_ahora > 0 or criticals_ahora > 0:
        current_potholes = potholes_ahora
        update_leds = True
            
        for label, values in detections.items():
            if label in ["critical", "pothole"] and len(values) > 0: 
                
                confidence = values[0].get("confidence")
                sensor_data = read_arduino_sensors()
                timestamp = datetime.now(UTC).isoformat()
                
                img_text = ""
                if frame_jpeg is not None:
                    img_text = base64.b64encode(frame_jpeg).decode('utf-8')

                entry = {
                    "label": label, "confidence": confidence, "timestamp": timestamp, 
                    "lat": sensor_data["latitude"], "lng": sensor_data["longitude"], "img_b64": img_text
                }
                
                save_to_db(entry)
                ui.send_message("detection", message={"content": label, "confidence": confidence, "timestamp": timestamp})
                break 

        time.sleep(5)

    elif current_potholes > 0:
        current_potholes = 0
        update_leds = True

# --- LA FUNCIÓ DEL BOTÓ ---
def end_trip_and_send():
    print("🛑 BOTÓ DE PÀRQUING PREMUT! Enviant dades a l'API...")
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  
    c = conn.cursor()
    files = c.execute("SELECT * FROM detections").fetchall()
    
    if len(files) == 0:
        print("✅ Ruta neta, res a enviar!")
        conn.close()
        return

    print(f"🔄 Enviant {len(files)} registres...")
    all_success = True

    for fila in files:
        payload = {
            "image_url": fila["image_base64"],  
            "gps": {"latitude": fila["lat"], "longitude": fila["lng"]},
            "timestamp": fila["timestamp"],
            "type_of_damage": fila["label"],
            "num_of_potholes": 1 if fila["label"] == "pothole" else 0,
            "num_of_signals": 1 if fila["label"] == "critical" else 0
        }
        
        try:
            response = requests.post(API_ENDPOINT, json=payload, timeout=5)
            if response.status_code not in [200, 201]:
                all_success = False
        except Exception as e:
            all_success = False
            
    if all_success:
        print("✅ Dades enviades correctament! Esborrant memòria local...")
        c.execute("DELETE FROM detections")
        conn.commit()
    else:
        print("⚠️ Hi ha hagut algun error amb l'API, les dades segueixen guardades.")
        
    conn.close()

init_db() 
detection_stream.on_detect_all(process_detections)

# Vinculem les comunicacions amb la placa
Bridge.provide("motion_started", set_moving)
Bridge.provide("motion_stopped", set_stopped)
Bridge.provide("leds_potholes", get_potholes_num)
Bridge.provide("do_leds_potholes", get_do_leds_potholes)

# AQUÍ ESCOLTEM EL BOTÓ FÍSIC
Bridge.provide("park_button_pressed", end_trip_and_send)

print("🚀 Sistema iniciat! Esperant moviment...")
App.run()
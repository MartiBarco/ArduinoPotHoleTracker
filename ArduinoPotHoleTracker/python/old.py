import json
import requests
import base64
import random
import sqlite3
import time  
from datetime import datetime, UTC
from arduino.app_utils import App, Bridge
from arduino.app_bricks.video_objectdetection import VideoObjectDetection
from arduino.app_bricks.web_ui import WebUI

API_ENDPOINT = "http://192.168.1.100:3000/api/potholes/batch"
DB_FILE = "viatges.db"

# --- ESTAT DE LA BICI I LEDS ---
is_moving = False 

# Noves variables d'estat per l'Arduino
current_potholes = 0
update_leds = False

detection_stream = VideoObjectDetection(confidence=0.5, debounce_sec=0.0, camera_preview=True)
ui = WebUI()
ui.on_message("override_th", lambda sid, threshold: detection_stream.override_threshold(threshold))


# --- BASE DE DADES SQLITE ---
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

def save_to_db(label, confidence, timestamp, lat, lng, img_b64):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO detections (label, confidence, timestamp, lat, lng, image_base64)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (label, confidence, timestamp, lat, lng, img_b64))
    conn.commit()
    conn.close()

# --- CONTROL DE MOVIMENT ---
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

# --- ENDPOINTS PER A L'ARDUINO ---

def get_potholes_num():
    """L'Arduino crida això per saber quants sots hi ha."""
    global current_potholes
    return current_potholes

def get_do_leds_potholes():
    """L'Arduino crida això per saber si ha d'actualitzar els LEDs."""
    global update_leds
    # Guardem l'estat actual i el reiniciem perquè l'Arduino no pitebi en bucle
    estat_actual = update_leds
    if update_leds:
        update_leds = False 
    return estat_actual

# --- LÒGICA DE DETECCIÓ I LEDS ---

def process_detections(detections: dict, frame_jpeg=None):
    global is_moving, current_potholes, update_leds
    
    if not is_moving:
        return 
        
    potholes_ahora = len(detections.get("pothole", []))
    criticals_ahora = len(detections.get("critical", []))
    
    # 1. SI HI HA SOTS (Potholes o Criticals detectats)
    if potholes_ahora > 0 or criticals_ahora > 0:
        
        # --- PREPARAR DADES PER L'ARDUINO ---
        current_potholes = potholes_ahora
        update_leds = True
        print(f"➡️ Senyal a LEDs preparada: {potholes_ahora} potholes")
        
        # --- GUARDAR EN LA BASE DE DATOS ---
        for label, values in detections.items():
            if label in ["critical", "pothole"]: 
                
                confidence = values[0].get("confidence")
                sensor_data = read_arduino_sensors()
                timestamp = datetime.now(UTC).isoformat()
                
                img_text = ""
                if frame_jpeg is not None:
                    img_text = base64.b64encode(frame_jpeg).decode('utf-8')

                entry = {
                    label=label, 
                    confidence=confidence, 
                    timestamp=timestamp, 
                    lat=sensor_data["latitude"], 
                    lng=sensor_data["longitude"], 
                    img_b64=img_text}
                
                save_to_db(entry)
                ui.send_message("detection", message=entry)
                break 

        print("💤 Durmiendo 5 segundos para no repetir la misma zona...")
        #time.sleep(5)  

    # 2. SI NO HI HA SOTS, PERÒ ELS LEDS CONTINUEN ENCESOS
    elif current_potholes > 0:
        current_potholes = 0
        update_leds = True  # Dispara l'Arduino perquè llegeixi el '0'
        print("🟢 Carretera neta. Senyal per apagar LEDs preparada.")  

# --- FINALITZACIÓ DEL VIATGE ---
def end_trip_and_send():
    global current_potholes, update_leds
    print("🚲 Preparant l'enviament de dades des de SQLite...")
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  
    c = conn.cursor()
    files = c.execute("SELECT * FROM detections").fetchall()
    
    if len(files) == 0:
        print("✅ Viatge finalitzat sense cap incidència. Ruta neta!")
        conn.close()
        return

    detection_history = []
    num_potholes = 0
    num_criticals = 0

    for fila in files:
        if fila["label"] == "pothole":
            num_potholes += 1
        elif fila["label"] == "critical":
            num_criticals += 1
            
        detection_history.append({
            "incident_type": fila["label"],
            "confidence": fila["confidence"],
            "timestamp": fila["timestamp"],
            "location": {"latitude": fila["lat"], "longitude": fila["lng"]},
            "image_base64": fila["image_base64"]
        })

    payload = {
        "bike_id": "bicing_001",
        "session_end": datetime.now(UTC).isoformat(),
        "run_info": {
            "totals": {
                "potholes": num_potholes,
                "critical": num_criticals,
                "total_records": len(detection_history)
            }
        },
        "detections": detection_history 
    }
    
    try:
        response = requests.post(API_ENDPOINT, json=payload, timeout=15)
        if response.status_code in [200, 201]:
            print("✅ API OK! Esborrant base de dades para el próximo viaje...")
            c.execute("DELETE FROM detections")
            conn.commit()
            
            # Apaguem els LEDs actualitzant l'estat perquè l'Arduino ho llegeixi
            current_potholes = 0
            update_leds = True
                
        else:
            print(f"⚠️ Error {response.status_code}. Las dades siguen seguras a SQLite.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error xarxa: {e}. Dades guardades a l'Arduino.")
        
    conn.close()

# --- ARRENCADA ---
init_db() 

detection_stream.on_detect_all(process_detections)

# Funcions que l'Arduino cridarà quan l'usuari faci alguna acció (Botons, moviment)
Bridge.provide("motion_started", set_moving)
Bridge.provide("motion_stopped", set_stopped)
Bridge.provide("park_button_pressed", end_trip_and_send)

# ENDPOINTS NOUS: Funcions que l'Arduino sondeja (polls) al seu void loop()
Bridge.provide("leds_potholes", get_potholes_num)
Bridge.provide("do_leds_potholes", get_do_leds_potholes)

print("🚀 Sistema iniciat! Esperando movimiento para activar la cámara...")
App.run()
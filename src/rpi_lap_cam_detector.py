from flask import Flask, Response, render_template_string
import threading
import cv2
import numpy as np
from picamera2 import Picamera2
import time
import psutil

app = Flask(__name__)

# === Config ===
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
LINE_X = FRAME_WIDTH // 2  # Vertical detection line, center by default
COOLDOWN_FRAMES = 15
MIN_CONFIDENCE = 0.4

# === Globals ===
output_frame = None
lock = threading.Lock()

reset_tracker_flag = False
new_tracker_type = None
recalibrate_flag = False

alert_active = False
cooldown = 0
tracker = None
crossing_history = []
direction = "N/A"

# System Monitoring Globals
cpu_usage_text = "Calculating..."
cpu_temp_text = "0"
mem_usage_text = "0"

# Window flag (if running with GUI)
showWindow = False
showWindow and cv2.startWindowThread()

# === HTML Template ===
HTML_PAGE = """
<!doctype html>
<title>Raspberry Pi Stream</title>
<h1>Live Object Tracking</h1>

<img src="{{ url_for('video_feed') }}" style="width: {{ width }}px;"><br><br>

<label for="trackerSelect">Tracker:</label>
<select id="trackerSelect" onchange="setTracker(this.value)">
  {% for t in trackers %}
    <option value="{{t}}" {% if t == current_tracker %}selected{% endif %}>{{t}}</option>
  {% endfor %}
</select>

<br><br>

<label for="lineSlider">Detection Line Position (X): <span id="lineValue">{{ line_x }}</span></label><br>
<input type="range" id="lineSlider" min="0" max="{{ width }}" value="{{ line_x }}" oninput="updateLine(this.value)" />

<br><br>

<button onclick="fetch('/reset_tracker')">Reset Tracker</button>
<button onclick="fetch('/recalibrate')">Recalibrate Background</button>

<script>
function setTracker(value) {
    fetch('/set_tracker?type=' + value)
        .then(response => response.text())
        .then(data => console.log(data));
}

function updateLine(value) {
    document.getElementById("lineValue").innerText = value;
    fetch('/set_line?x=' + value)
        .then(response => response.text())
        .then(data => console.log(data));
}
</script>
"""

# === Tracker Setup ===
def get_available_trackers():
    trackers = {
        'CSRT': cv2.legacy.TrackerCSRT_create if hasattr(cv2.legacy, 'TrackerCSRT_create') else None,
        'KCF': cv2.legacy.TrackerKCF_create if hasattr(cv2.legacy, 'TrackerKCF_create') else None,
        'MOSSE': cv2.legacy.TrackerMOSSE_create if hasattr(cv2.legacy, 'TrackerMOSSE_create') else None
    }
    return {name: create for name, create in trackers.items() if create}

AVAILABLE_TRACKERS = get_available_trackers()
TRACKER_TYPE = list(AVAILABLE_TRACKERS.keys())[0]

def init_tracker(frame, bbox):
    create_func = AVAILABLE_TRACKERS[TRACKER_TYPE]
    t = create_func()
    t.init(frame, bbox)
    return t

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read()) / 1000
    except FileNotFoundError:
        return None

# === Camera Setup ===
picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(main={
    "format": 'RGB888',
    "size": (FRAME_WIDTH, FRAME_HEIGHT)
}))
picam2.start()

# === Frame Capture Loop ===
def capture_frames():
    global output_frame, tracker, cooldown, alert_active
    global crossing_history, reset_tracker_flag, recalibrate_flag, direction, new_tracker_type, TRACKER_TYPE
    global cpu_usage_text, cpu_temp_text, mem_usage_text, LINE_X

    prev_frame_time = time.time()
    prev_monitoring_time = time.time()
    psutil.cpu_percent(interval=0, percpu=True)

    while True:
        frame = picam2.capture_array()

        # Tracker control flags
        if reset_tracker_flag:
            tracker = None
            crossing_history.clear()
            reset_tracker_flag = False
            print("INFO: Tracker reset.")

        if recalibrate_flag:
            if hasattr(init_tracker, 'avg'):
                del init_tracker.avg
            recalibrate_flag = False
            print("INFO: Background recalibration.")

        if new_tracker_type and new_tracker_type != TRACKER_TYPE:
            TRACKER_TYPE = new_tracker_type
            tracker = None
            crossing_history.clear()
            new_tracker_type = None
            print(f"INFO: Switched tracker to {TRACKER_TYPE}")

        if cooldown > 0:
            cooldown -= 1

        # Update tracker if available
        success = False
        if tracker is not None:
            success, bbox = tracker.update(frame)
            if success:
                x, y, w, h = [int(v) for v in bbox]
                center_x = x + w // 2
                left_cross = x <= LINE_X <= x + w
                right_cross = (x + w) >= LINE_X >= x
                direction = "RIGHT" if center_x > LINE_X else "LEFT"

                if (left_cross or right_cross) and cooldown == 0:
                    crossing_history.append(direction)
                    if len(crossing_history) > 5:
                        crossing_history.pop(0)
                    if len(set(crossing_history)) == 1:
                        alert_active = True
                        cooldown = COOLDOWN_FRAMES
                        print(f"ALERT: Object crossed line moving {direction}")
            else:
                tracker = None
                direction = "N/A"
        else:
            # Detect motion and initialize tracker
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            if not hasattr(init_tracker, 'avg'):
                init_tracker.avg = gray.copy().astype("float")
            cv2.accumulateWeighted(gray, init_tracker.avg, 0.5)
            frame_delta = cv2.absdiff(gray, cv2.convertScaleAbs(init_tracker.avg))
            thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for c in contours:
                if cv2.contourArea(c) > 1000:
                    (x, y, w, h) = cv2.boundingRect(c)
                    tracker = init_tracker(frame, (x, y, w, h))
                    break

        # Draw detection line
        cv2.line(frame, (LINE_X, 0), (LINE_X, FRAME_HEIGHT), (0, 255, 0), 2)
        cv2.putText(frame, f"Line @ X={LINE_X}", (10, FRAME_HEIGHT - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        if tracker and success:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(frame, "Object", (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        if alert_active:
            cv2.putText(frame, "CROSSING DETECTED", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            alert_active = False

        # System Monitoring every 2s
        if time.time() - prev_monitoring_time > 2:
            prev_monitoring_time = time.time()
            total_cpu = psutil.cpu_percent(interval=0)
            per_cpu = psutil.cpu_percent(interval=0, percpu=True)
            cpu_usage_text = f"CPU: {total_cpu:.1f}% ({', '.join(f'{u:.1f}' for u in per_cpu)})"
            cpu_temp = get_cpu_temp()
            cpu_temp_text = f"CPU temp: {cpu_temp:.1f} C" if cpu_temp else "CPU temp: N/A"
            memory = psutil.virtual_memory()
            mem_usage_text = f"Memory: {memory.percent:.1f}% ({memory.used // (1024 * 1024)} MB / {memory.total // (1024 * 1024)} MB)"

        # FPS
        curr_frame_time = time.time()
        fps = 1.0 / (curr_frame_time - prev_frame_time)
        prev_frame_time = curr_frame_time

        # Overlay Text
        cv2.putText(frame, f"Tracking: {direction if tracker else 'None'}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, f"FPS: {fps:.2f}", (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, f"Tracker: {TRACKER_TYPE}", (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, cpu_usage_text, (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, cpu_temp_text, (10, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, mem_usage_text, (10, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        with lock:
            output_frame = frame.copy()

        showWindow and cv2.imshow("Fast Object Tracking", frame)

# === Flask Routes ===
def generate_stream():
    global output_frame
    while True:
        with lock:
            if output_frame is None:
                continue
            _, buffer = cv2.imencode('.jpg', output_frame)
            frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template_string(HTML_PAGE,
        trackers=AVAILABLE_TRACKERS.keys(),
        current_tracker=TRACKER_TYPE,
        line_x=LINE_X,
        width=FRAME_WIDTH)

@app.route('/video_feed')
def video_feed():
    return Response(generate_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/reset_tracker')
def reset_tracker():
    global reset_tracker_flag
    reset_tracker_flag = True
    return "Tracker reset", 200

@app.route('/set_tracker')
def set_tracker():
    from flask import request
    global new_tracker_type
    tracker_type = request.args.get('type')
    if tracker_type in AVAILABLE_TRACKERS:
        new_tracker_type = tracker_type
        return f"Tracker set to {tracker_type}", 200
    return "Invalid tracker type", 400

@app.route('/recalibrate')
def recalibrate():
    global recalibrate_flag
    recalibrate_flag = True
    return "Recalibrated", 200

@app.route('/set_line')
def set_line():
    from flask import request
    global LINE_X
    try:
        LINE_X = int(request.args.get('x'))
        return f"Line X set to {LINE_X}", 200
    except:
        return "Invalid value", 400

# === Run App ===
if __name__ == '__main__':
    t = threading.Thread(target=capture_frames)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)

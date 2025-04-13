from flask import Flask, Response, render_template_string, request
import threading
import cv2
import numpy as np
from picamera2 import Picamera2
import time
import psutil
import subprocess

app = Flask(__name__)

# === Config ===
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
LINE_X = FRAME_WIDTH // 2  # Horizontal tracking
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

cpu_usage_text = "Calculating..."
cpu_temp_text = "N/A"
cpu_freqs_text = "0"
mem_usage_text = "0"
throttling_status_text = "Checking..."

# === Flask HTML Template ===
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

<h2>System Info:</h2>
<p><strong>CPU Usage:</strong> <span id="cpuUsage">{{ cpu_usage }}</span></p>
<p><strong>CPU Temperature:</strong> <span id="cpuTemp">{{ cpu_temp }}</span></p>
<p><strong>CPU Frequency:</strong> <span id="cpuFreq">{{ cpu_freq }}</span></p>
<p><strong>Memory Usage:</strong> <span id="memUsage">{{ mem_usage }}</span></p>
<p><strong>Throttle Status:</strong> <span id="throttlingStatus">{{ throttling_status }}</span></p>

<script>
function setTracker(value) {
    fetch('/set_tracker?type=' + value).then(r => r.text()).then(console.log);
}
function updateLine(value) {
    document.getElementById("lineValue").innerText = value;
    fetch('/set_line?x=' + value).then(r => r.text()).then(console.log);
}

function updateSystemInfo() {
    fetch('/get_status')
        .then(response => response.json())
        .then(data => {
            document.getElementById("cpuUsage").innerText = data.cpu_usage;
            document.getElementById("cpuTemp").innerText = data.cpu_temp;
            document.getElementById("cpuFreq").innerText = data.cpu_freq;
            document.getElementById("memUsage").innerText = data.mem_usage;
            document.getElementById("throttlingStatus").innerText = data.throttling_status;
        });
}

// Update the system info every 2 seconds
setInterval(updateSystemInfo, 2000);
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

# === System Info Functions ===
def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read()) / 1000
    except FileNotFoundError:
        return None

def get_throttling_status():
    try:
        out = subprocess.check_output(['vcgencmd', 'get_throttled']).decode()
        hex_value = int(out.strip().split('=')[1], 16)
        flags = {
            0x1: "Under-voltage",
            0x2: "Freq capped",
            0x4: "Throttled",
            0x8: "Temp soft limit",
            0x10000: "Under-voltage occurred",
            0x20000: "Freq cap occurred",
            0x40000: "Throttle occurred",
            0x80000: "Temp limit occurred"
        }
        messages = [msg for bit, msg in flags.items() if hex_value & bit]
        return "OK" if not messages else "; ".join(messages)
    except Exception as e:
        return f"Error: {e}"

def get_cpu_freq():
    freqs = psutil.cpu_freq(percpu=True)
    return ", ".join([f"{f.current:.0f} MHz" for f in freqs])

def get_status_text(fps, direction, tracker_type, cpu_usage, cpu_freq, cpu_temp, mem_usage, throttling_status):
    return (
        f"FPS: {fps:.2f}\n"
        f"Tracking: {direction}\n"
        f"Tracker: {tracker_type}\n"
        f"CPU: {cpu_usage}\n"
        f"CPU freq: {cpu_freq}\n"
        f"CPU temp: {cpu_temp}\n"
        f"RAM: {mem_usage}\n"
        f"Throttle: {throttling_status}"
    )

# === Camera Setup ===
picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(main={
    "format": 'RGB888',
    "size": (FRAME_WIDTH, FRAME_HEIGHT)
}))
picam2.start()

# === Monitoring Thread ===
def monitor_system():
    global cpu_usage_text, cpu_temp_text, cpu_freqs_text, mem_usage_text, throttling_status_text
    while True:
        cpu_usage = psutil.cpu_percent(interval=None)
        per_cpu = psutil.cpu_percent(interval=None, percpu=True)
        cpu_usage_text = f"{cpu_usage:.1f}% ({', '.join(f'{u:.1f}' for u in per_cpu)})"
        cpu_temp = get_cpu_temp()
        cpu_temp_text = f"{cpu_temp:.1f} C" if cpu_temp else "N/A"
        cpu_freqs_text = get_cpu_freq()  # Get the current CPU frequencies
        mem = psutil.virtual_memory()
        mem_usage_text = f"{mem.percent:.1f}% ({mem.used // (1024*1024)} MB / {mem.total // (1024*1024)} MB)"
        throttling_status_text = get_throttling_status()
        time.sleep(2)

# === Frame Capture Thread ===
def capture_frames():
    global output_frame, tracker, cooldown, alert_active
    global crossing_history, reset_tracker_flag, recalibrate_flag, direction, new_tracker_type, TRACKER_TYPE, LINE_X

    prev_frame_time = time.time()
    while True:
        frame = picam2.capture_array()

        if reset_tracker_flag:
            tracker = None
            crossing_history.clear()
            reset_tracker_flag = False

        if recalibrate_flag:
            if hasattr(init_tracker, 'avg'):
                del init_tracker.avg
            recalibrate_flag = False

        if new_tracker_type and new_tracker_type != TRACKER_TYPE:
            TRACKER_TYPE = new_tracker_type
            tracker = None
            crossing_history.clear()
            new_tracker_type = None

        if cooldown > 0:
            cooldown -= 1

        success = False
        if tracker:
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
            else:
                tracker = None
                direction = "N/A"
        else:
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

        # FPS
        curr_frame_time = time.time()
        fps = 1.0 / (curr_frame_time - prev_frame_time)
        prev_frame_time = curr_frame_time

        cv2.putText(frame, f"FPS: {fps:.2f}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        with lock:
            output_frame = frame.copy()

# === Flask Routes ===
@app.route('/get_status')
def get_status():
    return {
        'cpu_usage': cpu_usage_text,
        'cpu_temp': cpu_temp_text,
        'cpu_freq': cpu_freqs_text,
        'mem_usage': mem_usage_text,
        'throttling_status': throttling_status_text
    }

def generate_stream():
    global output_frame
    while True:
        with lock:
            if output_frame is None:
                continue
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 30]  # Default is 95
            _, buffer = cv2.imencode('.jpg', output_frame, encode_param)
            frame = buffer.tobytes()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/')
def index():
    return render_template_string(HTML_PAGE,
        trackers=AVAILABLE_TRACKERS.keys(),
        current_tracker=TRACKER_TYPE,
        line_x=LINE_X,
        width=FRAME_WIDTH,
        cpu_usage=cpu_usage_text,
        cpu_temp=cpu_temp_text,
        cpu_freq=cpu_freqs_text,
        mem_usage=mem_usage_text,
        throttling_status=throttling_status_text)

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
    global LINE_X
    try:
        LINE_X = int(request.args.get('x'))
        return f"Line X set to {LINE_X}", 200
    except:
        return "Invalid value", 400

# === Start Threads ===
if __name__ == '__main__':
    threading.Thread(target=monitor_system, daemon=True).start()
    threading.Thread(target=capture_frames, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, threaded=True)

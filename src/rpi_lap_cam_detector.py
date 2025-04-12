from flask import Flask, Response, render_template_string
import threading
import cv2
import numpy as np
from picamera2 import Picamera2
import time

import psutil

app = Flask(__name__)

# Globals
output_frame = None
lock = threading.Lock()

reset_tracker_flag = False
new_tracker_type = None
recalibrate_flag = False

# Tracker config
LINE_Y = 300
COOLDOWN_FRAMES = 15
MIN_CONFIDENCE = 0.4
alert_active = False
cooldown = 0
tracker = None
crossing_history = []
direction = "N/A"

# Desktop window
showWindow = False
showWindow and cv2.startWindowThread();

# HTML page
HTML_PAGE = """
<!doctype html>
<title>Raspberry Pi Stream</title>
<h1>Live Object Tracking</h1>
<img src="{{ url_for('video_feed') }}" style="width: 640px;"><br><br>

<label for="trackerSelect">Tracker:</label>
<select id="trackerSelect" onchange="setTracker(this.value)">
  {% for t in trackers %}
    <option value="{{t}}" {% if t == current_tracker %}selected{% endif %}>{{t}}</option>
  {% endfor %}
</select>

<button onclick="fetch('/reset_tracker')">Reset Tracker</button>
<button onclick="fetch('/recalibrate')">Recalibrate Background</button>

<script>
function setTracker(value) {
    fetch('/set_tracker?type=' + value)
        .then(response => response.text())
        .then(data => console.log(data));
}
</script>
"""


# Tracker setup
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
            temp = int(f.read()) / 1000
            return temp
    except FileNotFoundError:
        return None

# Camera setup
picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration(main={"format": 'RGB888', "size": (640, 480)}))
picam2.start()

def capture_frames():
    global output_frame, tracker, cooldown, alert_active
    global crossing_history, reset_tracker_flag, recalibrate_flag, direction, new_tracker_type, TRACKER_TYPE

    prev_frame_time = time.time()       # For FPS calculation
    prev_monitoring_time = time.time()  # For system monitoring
    psutil.cpu_percent(interval=0, percpu=True)
    global cpu_usage_text
    cpu_usage_text = "Calculating..."
    global cpu_temp_text
    cpu_temp_text = "0"
    global mem_usage_text
    mem_usage_text = "0"

    fps = 0

    while True:
        frame = picam2.capture_array()

        # Handle Tracker Reset
        if reset_tracker_flag:
            tracker = None
            crossing_history.clear()
            print("INFO: Tracker has been reset from web UI")
            reset_tracker_flag = False

        # Handle Background Recalibration
        if recalibrate_flag:
            if hasattr(init_tracker, 'avg'):
                del init_tracker.avg
            print("INFO: Background recalibration triggered from web UI")
            recalibrate_flag = False

        # Handle Tracker Change
        if new_tracker_type and new_tracker_type != TRACKER_TYPE:
            print(f"INFO: Switching tracker from {TRACKER_TYPE} to {new_tracker_type}")
            TRACKER_TYPE = new_tracker_type  # Update the global tracker type
            new_tracker_type = None
            tracker = None
            crossing_history.clear()

        if cooldown > 0:
            cooldown -= 1

        success = False
        if tracker is not None:
            success, bbox = tracker.update(frame)
            if success:
                x, y, w, h = [int(v) for v in bbox]
                center_y = y + h // 2
                top_cross = y <= LINE_Y <= y + h
                bottom_cross = (y + h) >= LINE_Y >= y
                direction = "DOWN" if center_y > LINE_Y else "UP"

                if (top_cross or bottom_cross) and cooldown == 0:
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

        # Draw line
        cv2.line(frame, (0, LINE_Y), (frame.shape[1], LINE_Y), (0, 255, 0), 2)
        cv2.putText(frame, f"Line @ Y={LINE_Y}", (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        if tracker is not None and success:
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
        fps_text = f"FPS: {fps:.2f}"

        # System Monitoring updates every 2 seconds
        if time.time() - prev_monitoring_time > 2:
            prev_monitoring_time = time.time()
            total_cpu = psutil.cpu_percent(interval=0)
            per_cpu = psutil.cpu_percent(interval=0, percpu=True)
            per_cpu_str = ", ".join(f"{usage:.1f}" for usage in per_cpu)
            cpu_usage_text = f"CPU: {total_cpu:.1f}% ({per_cpu_str})"
            cpu_temp_text = f"CPU temp: {get_cpu_temp():.1f} C" if get_cpu_temp() else "CPU temp: N/A"
            memory = psutil.virtual_memory()
            mem_usage_text = f"Memory: {memory.percent:.1f}% ({memory.used // (1024 * 1024)} MB / {memory.total // (1024 * 1024)} MB)"

        status_text = f"Tracking: {direction if tracker else 'None'}"
        tracker_name_text = f"Tracker: {TRACKER_TYPE}"


        cv2.putText(frame, status_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, fps_text, (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, tracker_name_text, (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, cpu_usage_text, (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, cpu_temp_text, (10, 150),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        cv2.putText(frame, mem_usage_text, (10, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

        # Output to stream
        with lock:
            output_frame = frame.copy()

        showWindow and cv2.imshow("Fast Object Tracking", frame)


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
        current_tracker=TRACKER_TYPE)

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

if __name__ == '__main__':
    t = threading.Thread(target=capture_frames)
    t.daemon = True
    t.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)

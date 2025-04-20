import queue
from flask import Flask, Response, render_template_string, request
import threading
import cv2
import numpy as np
from picamera2 import Picamera2
import time
import psutil
import subprocess
from enum import Enum, auto


app = Flask(__name__)

# === Config ===
FRAME_WIDTH = 1280  # Capture width, native being 1536 for a pi cam 3
FRAME_HEIGHT = 720  # Capture height, native being 864 for a pi cam 3
FRAME_SCALING = 0.5 # Scaling ratio for processing efficiency
FRAME_FPS = 60
DUAL_STREAM_MODE = False

LINE_X = FRAME_WIDTH // 2
MIN_Y = 0
MAX_Y = FRAME_HEIGHT
MIN_COUNTOUR_AREA = 500  # Minimum area of contour to consider for tracking

# === Streaming quality ===
STREAM_QUALITY = 35
STREAM_FPS_MAX = 35
STREAM_SCALING = 1
streaming_frame_queue = queue.Queue(maxsize=2)  # smoother than a lock

# === Globals ===
reset_tracker_flag = False
new_tracker_type = None
recalibrate_flag = False

last_crossing_time = None
last_crossing_direction = "N/A"
MOTION_HISTORY_LENGTH = 11          # No history with <=1. CPU intensive. Reduces false positives. Keep it at around 1/6th of the FPS.
CROSSING_FLASH_TIME = 0.5
COOL_DOWN_TIME = 1.0                # Seconds
TRACKING_TIMEOUT = 6.0              # Max time in the same tracker
TRACKING_RESILIENCE_LIMIT = 0.05    # Max time without tracking success before swtiching to DETECTING mode
TRACKER_TYPE = None
tracker = None
fps_global_string = "Calculating..."
MONITORING_INTERVAL = 2.5           # Seconds. Watch out for the CPU usage spike when changing this value.

last_status_time = 0
last_status_result = {}

# Tracker timing & movement
tracker_start_time = None
tracker_last_success_time = None
last_position = None

# === Flask HTML Template ===
HTML_PAGE = """
<!doctype html>
<title>Slotem Extremus Rpi</title>
<h1>Slotem Extremus Raspberry Pi detector</h1>

<div style="width: 100%; overflow: hidden;">
  <img src="{{ url_for('video_feed') }}" style="max-width: 100%; height: auto;" />
</div>

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
<label for="minYSlider">Minimum Y: <span id="minYValue">{{ min_y }}</span></label><br>
<input type="range" id="minYSlider" min="0" max="{{ height }}" value="{{ min_y }}" oninput="updateMinY(this.value)" />

<br><br>
<label for="maxYSlider">Maximum Y: <span id="maxYValue">{{ max_y }}</span></label><br>
<input type="range" id="maxYSlider" min="0" max="{{ height }}" value="{{ max_y }}" oninput="updateMaxY(this.value)" />

<br><br>
<button onclick="fetch('/reset_tracker')">Reset Tracker</button>
<button onclick="fetch('/recalibrate')">Recalibrate Background</button>
<button onclick="fetch('/reset_autofocus')">Reset Autofocus</button>

<h2>System Info:</h2>
<p><strong>FPS:</strong> <span id="fpsSummary">Calculating...</span></p>
<p><strong>CPU Usage:</strong> <span id="cpuUsage">Calculating...</span></p>
<p><strong>CPU Temperature:</strong> <span id="cpuTemp">N/A</span></p>
<p><strong>CPU Frequency:</strong> <span id="cpuFreq">0</span></p>
<p><strong>Memory Usage:</strong> <span id="memUsage">0</span></p>
<p><strong>Throttle Status:</strong> <span id="throttlingStatus">Checking...</span></p>

<script>
function setTracker(value) {
    fetch('/set_tracker?type=' + value).then(r => r.text()).then(console.log);
}
function updateLine(value) {
    document.getElementById("lineValue").innerText = value;
    fetch('/set_line?x=' + value).then(r => r.text()).then(console.log);
}
function updateMinY(value) {
    document.getElementById("minYValue").innerText = value;
    fetch('/set_min_y?y=' + value).then(r => r.text()).then(console.log);
}
function updateMaxY(value) {
    document.getElementById("maxYValue").innerText = value;
    fetch('/set_max_y?y=' + value).then(r => r.text()).then(console.log);
}
function updateSystemInfo() {
    fetch('/get_status')
        .then(response => response.json())
        .then(data => {
            document.getElementById("fpsSummary").innerText = data.fps_summary;
            document.getElementById("cpuUsage").innerText = data.cpu_usage;
            document.getElementById("cpuTemp").innerText = data.cpu_temp;
            document.getElementById("cpuFreq").innerText = data.cpu_freq;
            document.getElementById("memUsage").innerText = data.mem_usage;
            document.getElementById("throttlingStatus").innerText = data.throttling_status;
        });
}
setInterval(updateSystemInfo, 3000);
</script>
"""

class SystemMode(Enum):
    DETECTING = auto()
    TRACKING = auto()
    COOL_DOWN = auto()
mode_colors = {
    SystemMode.COOL_DOWN: (255, 0, 0),
    SystemMode.DETECTING: (0, 255, 255),
    SystemMode.TRACKING: (0, 255, 0),
}

# === Tracker Setup ===
def get_available_trackers():
    trackers = {
        'MOSSE': cv2.legacy.TrackerMOSSE_create if hasattr(cv2.legacy, 'TrackerMOSSE_create') else None,
        'CSRT': cv2.legacy.TrackerCSRT_create if hasattr(cv2.legacy, 'TrackerCSRT_create') else None,
        'KCF': cv2.legacy.TrackerKCF_create if hasattr(cv2.legacy, 'TrackerKCF_create') else None
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
    try:
        out = subprocess.check_output(['vcgencmd', 'measure_clock', 'arm']).decode()
        cpu_freq = int(out.strip().split('=')[1]) / 1000000
        per_cpu = psutil.cpu_freq(percpu=True)
        max_freq = per_cpu[0].max if per_cpu else 0
        return f"{cpu_freq:.0f} / {max_freq} MHz"
    except Exception as e:
        return f"Error: {e}"

def reset_autofocus():
    try:
        picam2.set_controls({"AfMode": 1})  # Continuous autofocus mode
        picam2.set_controls({"AfTrigger": 0})  # Cancel any current AF action
        time.sleep(0.1)
        picam2.set_controls({"AfTrigger": 1})  # Start a new AF cycle
        print("Autofocus reset triggered.")
    except Exception as e:
        print(f"Error resetting autofocus: {e}")

# === Camera Setup ===
picam2 = Picamera2()
print(picam2.sensor_modes)
if not DUAL_STREAM_MODE:
    config = picam2.create_preview_configuration(
       main={
            "format": 'RGB888',
            "size": (FRAME_WIDTH, FRAME_HEIGHT)
        },
        controls={"FrameRate": FRAME_FPS},
#        buffer_count=10,   # Buffer count for preview
#        queue=False,       # Risky...
    )
else:
    config = picam2.create_preview_configuration(
       main={
            "format": 'RGB888',
            "size": (FRAME_WIDTH, FRAME_HEIGHT)
        },
        lores={
            "format": 'YUV420',
            "size": (int(FRAME_WIDTH*FRAME_SCALING), int(FRAME_HEIGHT*FRAME_SCALING))
        },
        controls={"FrameRate": FRAME_FPS}
    )
picam2.configure(config)
picam2.start()

current_mode = SystemMode.COOL_DOWN
cooldown_until = 0

def capture_frames():
    global tracker, last_crossing_time
    global reset_tracker_flag, recalibrate_flag
    global last_crossing_direction, new_tracker_type, TRACKER_TYPE, LINE_X
    global tracker_start_time, last_position, tracker_last_success_time
    global fps_global_string
    global current_mode, cooldown_until

    prev_frame_time = time.time()
    prev_streamed_time = time.time()

    fps_temp_counter = 0
    fps_temp_start = time.time()
    fps_temp_slowest_frame = 1

    print(">>> COOL_DOWN mode set to start")
    cooldown_until = time.time() + COOL_DOWN_TIME

    motion_history = []

    while True:
        current_frame_time = time.time()
        current_frame = picam2.capture_array("main")

        if DUAL_STREAM_MODE:
            current_frame_resized = picam2.capture_array("lores")
            width, height = picam2.stream_configuration("lores")["size"]
            current_frame_gray = current_frame_resized[:height, :width] # Efficient grayscale extraction from YUV402 to avoid color conversion
        else:
            # consider INTER_LINEAR
            current_frame_resized = cv2.resize(current_frame, (int(current_frame.shape[1] * FRAME_SCALING), int(current_frame.shape[0] * FRAME_SCALING)), interpolation=cv2.INTER_AREA)
            current_frame_gray = cv2.cvtColor(current_frame_resized, cv2.COLOR_BGR2GRAY)

        if reset_tracker_flag:
            tracker = None
            motion_history.clear()
            tracker_start_time = None
            last_position = None
            reset_tracker_flag = False

        if recalibrate_flag:
            if hasattr(init_tracker, 'avg'):
                del init_tracker.avg
            motion_history.clear()
            recalibrate_flag = False

        if new_tracker_type and new_tracker_type != TRACKER_TYPE:
            TRACKER_TYPE = new_tracker_type
            tracker = None
            tracker_start_time = None
            last_position = None
            new_tracker_type = None

        if current_mode == SystemMode.COOL_DOWN and current_frame_time >= cooldown_until:
            current_mode = SystemMode.DETECTING
            if hasattr(init_tracker, 'avg'):
                del init_tracker.avg    # Recalibrating after every cool down
            motion_history.clear()
            print(">>> DETECTING mode after COOL_DOWN finished")


        #
        # TRACKING
        #

        if current_mode == SystemMode.TRACKING:
            success, bbox = tracker.update(current_frame_gray)
            if success:
                x, y, w, h = [int(v) for v in bbox]
                center_x = x + w // 2
                center_y = y + h // 2

                # Check if object has left the visible frame
                frame_height, frame_width = current_frame_gray.shape[:2]
                if not (0 <= center_x < frame_width and 0 <= center_y < frame_height):
                    print(">>> COOL_DOWN mode after object left the frame")
                    current_mode = SystemMode.COOL_DOWN
                    cooldown_until = current_frame_time + COOL_DOWN_TIME
                    tracker = None
                    tracker_start_time = None
                    last_position = None
                    last_crossing_direction = "N/A"
                    continue

                # Detect crossing the line
                if last_position:
                    prev_x = last_position[0]
                    if prev_x < LINE_X * FRAME_SCALING and center_x >= LINE_X * FRAME_SCALING:
                        last_crossing_direction = "RIGHT"
                        last_crossing_time = current_frame_time
                        print(f">>> Object crossed line from LEFT to RIGHT")
                    elif prev_x > LINE_X * FRAME_SCALING and center_x <= LINE_X * FRAME_SCALING:
                        last_crossing_direction = "LEFT"
                        last_crossing_time = current_frame_time
                        print(f">>> Object crossed line from RIGHT to LEFT")
                    else:
                        last_crossing_direction = "N/A"

                # Check if the tracker has been active for too long
                if tracker_start_time and current_frame_time - tracker_start_time > TRACKING_TIMEOUT:
                    current_mode = SystemMode.COOL_DOWN
                    print(">>> COOL_DOWN mode after tracker timeout")
                    cooldown_until = current_frame_time + COOL_DOWN_TIME
                    tracker = None
                    tracker_start_time = None
                    last_position = None
                    last_crossing_direction = "N/A"
                    continue

                last_position = (center_x, center_y)
                tracker_last_success_time = current_frame_time

            else:
                # Tracking failed
                if tracker_last_success_time and current_frame_time - tracker_last_success_time > TRACKING_RESILIENCE_LIMIT:
                    current_mode = SystemMode.DETECTING
                    print(">>> DETECTING mode after tracking resilience limit exceeded")
                    tracker = None
                    tracker_start_time = None
                    last_position = None
                    last_crossing_direction = "N/A"


        #
        # DETECTION
        #

        elif current_mode == SystemMode.DETECTING:
            blur = cv2.GaussianBlur(current_frame_gray, (21, 21), 0)

            if not hasattr(init_tracker, 'avg'):
                init_tracker.avg = blur.copy().astype("float")

            cv2.accumulateWeighted(blur, init_tracker.avg, 0.2)
            frame_delta = cv2.absdiff(blur, cv2.convertScaleAbs(init_tracker.avg))
            thresh = cv2.threshold(frame_delta, 15, 255, cv2.THRESH_BINARY)[1]

            # Motion detection
            if MOTION_HISTORY_LENGTH > 1:
                # Save motion frame to history, and don't do anything else if not enough frames
                motion_history.append(thresh.copy())
                if len(motion_history) > MOTION_HISTORY_LENGTH:
                    motion_history.pop(0)
                elif len(motion_history) < MOTION_HISTORY_LENGTH:
                    continue
                # Combine all motion masks
                motion = np.bitwise_or.reduce(motion_history)    # NEW
            else:
                motion = cv2.dilate(thresh, None, iterations=2)

            # Find contours on the  motion
            contours, _ = cv2.findContours(motion, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            largest_contour = None
            max_area = 0

            for c in contours:
                area = cv2.contourArea(c)
                if area > (MIN_COUNTOUR_AREA * FRAME_SCALING * FRAME_SCALING) and area > max_area:
                    largest_contour = c
                    max_area = area

            if largest_contour is not None:
                (x, y, w, h) = cv2.boundingRect(largest_contour)

                # Optional: expand the box a bit
                pad_x = int(w * 0.3)
                pad_y = int(h * 0.2)
                x = max(x - pad_x, 0)
                y = max(y - pad_y, 0)
                w = min(w + 2 * pad_x, current_frame_gray.shape[1] - x)
                h = min(h + 2 * pad_y, current_frame_gray.shape[0] - y)

                if y < MIN_Y * FRAME_SCALING or y + h > MAX_Y * FRAME_SCALING:
                    pass  # outside Y range
                else:
                    try:
                        tracker = init_tracker(current_frame_gray, (x, y, w, h))
                        tracker_start_time = current_frame_time
                        tracker_last_success_time = current_frame_time
                        last_position = None
                        current_mode = SystemMode.TRACKING
                        print(">>> TRACKING mode after largest averaged contour found")
                    except Exception as e:
                        print(f">>> Tracker init failed: {e}. Staying in DETECTING mode.")


        #
        # POST-PROCESSING
        #

        # Flash on detection
        if last_crossing_time and abs(last_crossing_time - current_frame_time) < CROSSING_FLASH_TIME:
            alpha = 1.0 - (abs(last_crossing_time - current_frame_time) / CROSSING_FLASH_TIME)
            overlay = np.full_like(current_frame, 255)  # White overlay
            cv2.addWeighted(overlay, alpha, current_frame, 1 - alpha, 0, current_frame)

        # Lines
        cv2.line(current_frame, (0, MIN_Y), (FRAME_WIDTH, MIN_Y), (0, 0, 255), 2)
        cv2.line(current_frame, (0, MAX_Y), (FRAME_WIDTH, MAX_Y), (0, 0, 255), 2)
        cv2.line(current_frame, (LINE_X, 0), (LINE_X, FRAME_HEIGHT), (0, 255, 0), 2)

        # Bounding box
        if tracker and last_position:
            cv2.rectangle(current_frame, (int(x/FRAME_SCALING), int(y/FRAME_SCALING)), (int(x/FRAME_SCALING + w/FRAME_SCALING), int(y/FRAME_SCALING + h/FRAME_SCALING)), (0, 255, 0), 2)
            cv2.putText(current_frame, "Movida", (int(x/FRAME_SCALING), int(y/FRAME_SCALING) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        # Time and FPS calculation
        curr_frame_time = time.time()
        frame_duration = curr_frame_time - prev_frame_time
        fps = 1.0 / frame_duration if frame_duration > 0 else 0.0
        prev_frame_time = curr_frame_time

        # Stats accumulation
        fps_temp_counter += 1
        fps_temp_slowest_frame = max(fps_temp_slowest_frame, frame_duration)

        # Periodic monitoring output
        elapsed_monitoring = curr_frame_time - fps_temp_start
        if elapsed_monitoring > 0:
            avg_fps = fps_temp_counter / elapsed_monitoring
            min_fps = 1.0 / fps_temp_slowest_frame if fps_temp_slowest_frame > 0 else 0.0
            fps_string = f"FPS last/avg/min: {fps:.1f}/{avg_fps:.1f}/{min_fps:.1f}"
        else:
            fps_string = f"FPS: {fps:.1f}"

        # Print and reset after interval
        if elapsed_monitoring >= MONITORING_INTERVAL:
            fps_global_string = fps_string
            print(fps_global_string)
            fps_temp_counter = 0
            fps_temp_slowest_frame = 0
            fps_temp_start = curr_frame_time

        # Display FPS on the frame
        color = mode_colors.get(current_mode, (255, 255, 255))
        cv2.putText(current_frame, f"{fps_string}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)

#       Theoritecally correct, but slower        
#        try:
#            frame_queue.put_nowait(frame.copy())
#        except queue.Full:
#            pass  # just skip, or log dropped frames
        if curr_frame_time - prev_streamed_time >= 1.0/STREAM_FPS_MAX and not streaming_frame_queue.full():
            prev_streamed_time = curr_frame_time
            streaming_frame_queue.put_nowait(current_frame.copy())

        time.sleep(0.001)   # Avoid suffocating the CPU


# === Flask Routes ===
def generate_stream():
    try:
        while True:
            current_time = time.time()
            try:
                output_frame_copy = streaming_frame_queue.get(timeout=1)
            except queue.Empty:
                continue

            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_QUALITY]
            _, buffer = cv2.imencode('.jpg', output_frame_copy, encode_param)
            frame = buffer.tobytes()

            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    except GeneratorExit:
        print("Client disconnected from video stream")
    except Exception as e:
        print(f"Streaming error: {e}")



@app.route('/get_status')
def get_status():
    global last_status_time, last_status_result
    current_time = time.time()

    if current_time - last_status_time >= MONITORING_INTERVAL:
        cpu_usage = psutil.cpu_percent(interval=None)
        per_cpu = psutil.cpu_percent(interval=None, percpu=True)
        cpu_usage_text = f"{cpu_usage:.1f}% ({', '.join(f'{u:.1f}' for u in per_cpu)})"

        cpu_temp = get_cpu_temp()
        cpu_temp_text = f"{cpu_temp:.1f} C" if cpu_temp else "N/A"

        cpu_freqs_text = get_cpu_freq()

        mem = psutil.virtual_memory()
        mem_usage_text = f"{mem.percent:.1f}% ({mem.used // (1024*1024)} MB / {mem.total // (1024*1024)} MB)"

        throttling_status_text = get_throttling_status()

        last_status_result = {
            'cpu_usage': cpu_usage_text,
            'cpu_temp': cpu_temp_text,
            'cpu_freq': cpu_freqs_text,
            'mem_usage': mem_usage_text,
            'throttling_status': throttling_status_text,
            'fps_summary': fps_global_string
        }

        last_status_time = current_time

    return last_status_result


@app.route('/')
def index():
    return render_template_string(HTML_PAGE,
        trackers=AVAILABLE_TRACKERS.keys(),
        current_tracker=TRACKER_TYPE,
        line_x=LINE_X,
        min_y=MIN_Y,
        max_y=MAX_Y,
        width=int(FRAME_WIDTH*STREAM_SCALING),
        height=int(FRAME_HEIGHT*STREAM_SCALING),
        cpu_usage="Calculating...",
        cpu_temp="N/A",
        cpu_freq="0",
        mem_usage="0",
        throttling_status="Checking...",
        fps_summary=fps_global_string)


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

@app.route('/set_min_y')
def set_min_y():
    global MIN_Y
    try:
        MIN_Y = int(request.args.get('y'))
        return f"Min Y set to {MIN_Y}", 200
    except:
        return "Invalid value", 400

@app.route('/set_max_y')
def set_max_y():
    global MAX_Y
    try:
        MAX_Y = int(request.args.get('y'))
        return f"Max Y set to {MAX_Y}", 200
    except:
        return "Invalid value", 400

@app.route('/reset_autofocus')
def reset_autofocus_route():
    reset_autofocus()
    return "Autofocus reset", 200

# === Start Threads ===
if __name__ == '__main__':
    threading.Thread(target=capture_frames, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, threaded=True)

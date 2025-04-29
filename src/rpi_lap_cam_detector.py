import queue
from flask import Flask, Response, render_template_string, request
import threading
import cv2
import numpy as np
from picamera2 import Picamera2
import time
import psutil
import subprocess
import requests
from enum import Enum, auto


app = Flask(__name__)

# === Config ===
FRAME_WIDTH = 1280  # Capture width, native being 1536 for a pi cam 3
FRAME_HEIGHT = 720  # Capture height, native being 864 for a pi cam 3
FRAME_SCALING = 0.4 # Scaling ratio for processing efficiency
FRAME_FPS = 60      # FPS target
DUAL_STREAM_MODE = False
DETECT_WHILE_TRACKING = False  # If True, will use detection while tracking. Contours will expand, but it will be CPU heavy and needs tweaking here and there!

META_LINE_X_PX = 800                # X position of the detection line, in pixels
MIN_Y_FACTOR = 0.20                # Minimum Y position of the detection line, in percentage
MAX_Y_FACTOR = 0.85                # Maximum Y position of the detection line, in percentage
WIDTH_OFFSET = 0.60         # Offset for the width of the detection line, in percentage, to mitigate detecting only fronts of the cars
MIN_COUNTOUR_AREA = 0.02    # Minimum area of contour to consider for tracking, in percentage of the frame size

# === Streaming quality ===
STREAM_QUALITY = 35
STREAM_EVERY_X_FRAMES = 3   # It will stream only every {x} frames
STREAM_SCALING = 0.4
streaming_frame_queue = queue.Queue(maxsize=2)  # smoother than a lock

# === Globals ===
trigger_cooldown = False
new_tracker_type = None
recalibrate_flag = False

MOTION_HISTORY_LENGTH = 0           # No contour change with 0. Dilate with 1. Real motion history with >1.
CROSSING_FLASH_TIME = 0.4           # Seconds
COOL_DOWN_TIME = 1.0                # Seconds
TRACKING_TIMEOUT = 5.0              # Max time in the same tracker
TRACKING_RESILIENCE_LIMIT = 0.05    # Max time without tracking success before swtiching to DETECTING mode
DETECT_SHADOWS = False              # For the background substractor config
TRACKER_TYPE = None
tracker = None
fps_global_string = "Calculating..."
MONITORING_INTERVAL = 2.5           # Seconds. Watch out for the CPU usage spike when changing this value.

last_status_time = 0
last_status_result = {}

# Tracker timing & movement
tracker_start_time = None
tracker_last_success_time = None
last_bbox_in_subframe_coordinates = None

# After motion detection, tracking, etc. frames are queued for processing
post_processing_queue = queue.Queue(maxsize=0)

# Meta crossing queue, holding the last frame with a crossing and lots of additional data
meta_crossing_queue = queue.Queue(maxsize=0)

# Queue with the list of pending events to be sent to the server
pending_events_queue = queue.Queue(maxsize=0)


# === Flask HTML Template ===
HTML_PAGE = """
<!doctype html>
<title>Slotem Extremus Rpi</title>
<h1>Slotem Extremus Raspberry Pi detector</h1>

<div style="width: 100%; overflow: hidden;">
  <img src="{{ url_for('video_feed') }}" style="max-width: 100%; height: auto;" />
</div>

<div style="display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 20px;">
  <button onclick="fetch('/trigger_cooldown')">Cooldown</button>
  <button onclick="fetch('/recalibrate')">Recalibrate Background</button>
  <button onclick="fetch('/reset_autofocus')">Reset Autofocus</button>
</div>

<div style="display: flex; gap: 40px; align-items: flex-start; flex-wrap: wrap;">

  <!-- Detection Config Panel -->
  <div style="flex: 1; min-width: 300px;">
    <h2>Detection Config</h2>

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
    <label for="minYSlider">Minimum Y: <span id="minYValue">{{ min_y }}</span>%</label><br>
    <input type="range" id="minYSlider" min="0" max="100" value="{{ min_y }}" oninput="updateMinY(this.value)" />

    <br><br>
    <label for="maxYSlider">Maximum Y: <span id="maxYValue">{{ max_y }}</span>%</label><br>
    <input type="range" id="maxYSlider" min="0" max="100" value="{{ max_y }}" oninput="updateMaxY(this.value)" />
  </div>

  <!-- System Status Panel -->
  <div style="flex: 1; min-width: 300px;">
    <h2>System Status</h2>
    <p><strong>Performance:</strong> <span id="fpsSummary">Calculating...</span></p>
    <p><strong>CPU Usage:</strong> <span id="cpuUsage">Calculating...</span></p>
    <p><strong>CPU Temperature:</strong> <span id="cpuTemp">N/A</span></p>
    <p><strong>CPU Frequency:</strong> <span id="cpuFreq">0</span></p>
    <p><strong>Memory Usage:</strong> <span id="memUsage">0</span></p>
    <p><strong>Throttle Status:</strong> <span id="throttlingStatus">Checking...</span></p>
  </div>

</div>

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
    SystemMode.COOL_DOWN: (255, 255, 0),
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

# === Bounding Box Functions ===
def bbox_contains(box_a, box_b):
    if box_a is None:
        return False

    if box_b is None:
        return True

    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b

    # Bottom-right corners
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = by + bh, by + bh

    # Check if all corners of B are within A
    return (bx >= ax and by >= ay and
            bx + bw <= ax2 and
            by + bh <= ay2)

def bbox_intersects(box_a, box_b):
    if box_a is None or box_b is None:
        return False
    
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b

    # Bottom-right corners
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    # Check if there's an overlap
    return not (ax2 < bx or bx2 < ax or ay2 < by or by2 < ay)

def bbox_is_larger(box_a, box_b):
    if box_a is None:
        return False

    if box_b is None:
        return True

    # Check if A is larger than B
    return (box_a[2] * box_a[3]) > (box_b[2] * box_b[3])

def bbox_area(box):
    if box is None:
        return 0
    return box[2] * box[3]

def bbox_center(box):
    if box is None:
        return None
    x, y, w, h = box
    return (x + w // 2, y + h // 2)

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



#
# MAIN FUNCTION
#
def capture_frames():
    global tracker
    global trigger_cooldown, recalibrate_flag
    global new_tracker_type, TRACKER_TYPE, META_LINE_X_PX, DETECT_SHADOWS
    global tracker_start_time, last_bbox_in_subframe_coordinates, tracker_last_success_time
    global fps_global_string

    prev_frame = None
    curr_frame = None
    prev_frame_time = time.time()
    last_crossing_time = None

    fps_temp_counter = 0
    fps_temp_start = time.time()
    fps_temp_slowest_frame = 1

    print(">>> COOL_DOWN mode set to start")
    trigger_cooldown = True
    curr_mode = SystemMode.COOL_DOWN


    motion_history = []

    # Background subtraction
    # Use MOG2 for better performance in low light conditions
    # Use KNN for better performance in bright light conditions
    # Use MOG for better performance in high motion conditions
    # history: Number of frames to use for background modeling.
    # varThreshold: Higher = less sensitive to movement.
    # detectShadows: If True, shadows will be marked gray (127), not white (255).
    #background = cv2.createBackgroundSubtractorKNN(history=50, dist2Threshold=200.0, detectShadows=DETECT_SHADOWS)
    background = cv2.createBackgroundSubtractorMOG2(history=150, varThreshold=32, detectShadows=DETECT_SHADOWS)

#    picam2.set_controls({
#        "AeEnable": False,         # Auto exposure OFF
#        "ExposureTime": 1000,     # Set manually, tune for lighting
#        "AnalogueGain": 1.0,       # Optional: fixed gain
#        "AwbEnable": False         # Auto white balance OFF (optional)
#    })

    while True:

        #
        # FRAME ACQUISITION
        #

        curr_frame_time = time.time()
        prev_frame = curr_frame
        curr_frame = picam2.capture_array("main")
        curr_scaled_frame_width = int(curr_frame.shape[1] * FRAME_SCALING)
        curr_scaled_frame_height = int(curr_frame.shape[0] * FRAME_SCALING)
        scaled_meta_line_x = int(META_LINE_X_PX * FRAME_SCALING)
        min_scaled_y = int(curr_scaled_frame_height * MIN_Y_FACTOR)
        max_scaled_y = int(curr_scaled_frame_height * MAX_Y_FACTOR)
        min_scaled_x = int(scaled_meta_line_x * (1.0 - WIDTH_OFFSET))
        max_scaled_x = scaled_meta_line_x + int(WIDTH_OFFSET * (curr_scaled_frame_width - scaled_meta_line_x))
        min_accepted_area = int(curr_scaled_frame_width * curr_scaled_frame_height * MIN_COUNTOUR_AREA)


        # Resize and crop for processing
        if DUAL_STREAM_MODE:
            current_frame_resized = picam2.capture_array("lores")
            curr_subframe_gray = current_frame_resized[min_scaled_y:max_scaled_y, :curr_scaled_frame_width]

        else:
            # Blur the image before resizing to clean some noise, as it comes from high frame rate video
            blurred_image = cv2.GaussianBlur(curr_frame, (5, 5), 0)
            # Resize frame
            current_frame_resized = cv2.resize(
                blurred_image,
                (
                    curr_scaled_frame_width,
                    curr_scaled_frame_height
                ),
                interpolation=cv2.INTER_LINEAR  # INTER_AREA gives more quality, but we don't need it
            )

            # Convert to grayscale
            curr_subframe_gray = cv2.cvtColor(current_frame_resized, cv2.COLOR_BGR2GRAY)

            # Crop vertically
            curr_subframe_gray = curr_subframe_gray[min_scaled_y:max_scaled_y, :]

        curr_subframe_height, curr_subframe_width = curr_subframe_gray.shape[:2]



        #
        # VARIABLE INITIALIZATION
        #

        if trigger_cooldown:
            motion_history.clear()
            curr_mode = SystemMode.COOL_DOWN
            cooldown_until = curr_frame_time + COOL_DOWN_TIME
            tracker = None
            tracker_start_time = None
            last_bbox_in_subframe_coordinates = None
            tracker_last_success_time = None
            trigger_cooldown = False
            picam2.set_controls({"AeEnable": True, "AwbEnable": True})          # Enable auto exposure and white balance only during COOL_DOWN

        if recalibrate_flag:        ### NOT NEEDED - KEPT AS PLACEHOLDER FOR ANOTHER BUTTON
            background = cv2.createBackgroundSubtractorKNN(history=100, dist2Threshold=400.0, detectShadows=DETECT_SHADOWS)
            trigger_cooldown = True
            recalibrate_flag = False
            continue

        if new_tracker_type and new_tracker_type != TRACKER_TYPE:
            TRACKER_TYPE = new_tracker_type
            tracker = None
            tracker_start_time = None
            last_bbox_in_subframe_coordinates = None
            new_tracker_type = None



        #
        # COOL DOWN
        #

        if curr_mode == SystemMode.COOL_DOWN:
            # Feed the background substractor (only in cool down - tracking would polute the background))
            last_background_thresh = background.apply(curr_subframe_gray)
            if curr_frame_time >= cooldown_until:
                picam2.set_controls({"AeEnable": False, "AwbEnable": False})    # Disable auto exposure and white balance
                curr_mode = SystemMode.DETECTING
                print(">>> DETECTING mode after COOL_DOWN finished")



        #
        # TRACKING
        #

        elif curr_mode == SystemMode.TRACKING:
            # Check if the tracker has been active for too long
            if tracker_start_time and curr_frame_time - tracker_start_time > TRACKING_TIMEOUT:
                print(">>> TRACKING -> COOL_DOWN mode after tracker timeout")
                trigger_cooldown = True
                continue

            success, new_bbox = tracker.update(curr_subframe_gray)
            if success:
                # Check if object has left the visible frame
                center_x, center_y = bbox_center(new_bbox)
                if not (0 <= center_x < curr_subframe_width and 0 <= center_y < curr_subframe_height):
                    print(">>> TRACKING -> COOL_DOWN mode after object left the frame")
                    trigger_cooldown = True
                    continue

                # Detect crossing the line
                if last_bbox_in_subframe_coordinates:
                    prev_x1 = last_bbox_in_subframe_coordinates[0]
                    prev_x2 = prev_x1 + last_bbox_in_subframe_coordinates[2]
                    new_x1 = new_bbox[0]
                    new_x2 = new_x1 + new_bbox[2]
                    if prev_x2 < scaled_meta_line_x and new_x2 >= scaled_meta_line_x:
                        last_crossing_time = curr_frame_time
                        tracker_start_time = curr_frame_time         # Extend the TTL of the tracker
                        print(f"--> CROSSING from LEFT to RIGHT")
                    elif prev_x1 > scaled_meta_line_x and new_x1 <= scaled_meta_line_x:
                        last_crossing_time = curr_frame_time
                        tracker_start_time = curr_frame_time         # Extend the TTL of the tracker
                        print(f"--> CROSSING from RIGHT to LEFT")

                last_bbox_in_subframe_coordinates = new_bbox
                tracker_last_success_time = curr_frame_time

            else:
                # Tracking failed
                if tracker_last_success_time and curr_frame_time - tracker_last_success_time > TRACKING_RESILIENCE_LIMIT:
                    curr_mode = SystemMode.DETECTING
                    print(">>> TRACKING -> DETECTING mode after tracking resilience limit exceeded")
                    tracker = None
                    tracker_start_time = None
                    last_bbox_in_subframe_coordinates = None


        #
        # DETECTION
        #

        if curr_mode == SystemMode.DETECTING or (DETECT_WHILE_TRACKING and curr_mode == SystemMode.TRACKING):

#            diff = cv2.absdiff(background.getBackgroundImage(), curr_subframe_gray)
#            last_background_thresh = cv2.GaussianBlur(diff, (5, 5), 0)
            last_background_thresh = background.apply(curr_subframe_gray, learningRate=0)

            # Clean the background
            if DETECT_SHADOWS:  # Removes shadows (if detectShadows=True)
                last_background_thresh = cv2.threshold(last_background_thresh, 200, 255, cv2.THRESH_BINARY)[1]
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            # back_sub_thresh = cv2.morphologyEx(back_sub_thresh, cv2.MORPH_OPEN, kernel)   # Combines erosion & dilation
            last_background_thresh = cv2.morphologyEx(last_background_thresh, cv2.MORPH_CLOSE, kernel)  # Combines dilation & erosion
            # back_sub_thresh = cv2.dilate(back_sub_thresh, None, iterations=2)             # Removes noise
            # last_background_thresh = cv2.erode(last_background_thresh, None, iterations=2)              # Erode to remove noise

            # Optional motion detection
            if MOTION_HISTORY_LENGTH > 1:
                if curr_mode != SystemMode.TRACKING:  # Do NOT update motion history if we're in TRACKING mode (when combining tracking and detection)
                    motion_history.append(last_background_thresh.copy())
                if len(motion_history) > MOTION_HISTORY_LENGTH:
                    motion_history.pop(0)
                # Combine all motion masks
                last_background_thresh = np.bitwise_or.reduce(motion_history)

            # Find contours only when we're not waiting for the motion history to build up
            contours = []
            if not (MOTION_HISTORY_LENGTH > 1 and len(motion_history) < MOTION_HISTORY_LENGTH):
                contours, _ = cv2.findContours(last_background_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            largest_contour = None
            max_area = 0
            for c in contours:
                bbox = cv2.boundingRect(c)
                area = bbox_area(bbox)

                if (area > max_area and                     # Getting the largest contour
                    area > min_accepted_area and            # Min area requirement
                    (bbox[1]+bbox[2]) > min_scaled_x and    # Not too close to the left edge
                    bbox[0] < max_scaled_x):                # Not too close to the right edge
                    largest_contour = c
                    max_area = area

            # If we didn't find contours, we use this frame to build the background
            if len(contours) == 0:
                background.apply(curr_subframe_gray, learningRate=0.01)

            # Note that the last bbox will either be empty or will be overridable when combining tracking and detection is enabled
            if max_area > 0 and max_area >= bbox_area(last_bbox_in_subframe_coordinates):
                try:
                    last_bbox_in_subframe_coordinates = cv2.boundingRect(largest_contour)
                    tracker = init_tracker(curr_subframe_gray, last_bbox_in_subframe_coordinates)
                    tracker_start_time = curr_frame_time
                    tracker_last_success_time = curr_frame_time
                    curr_mode = SystemMode.TRACKING
                    print(">>> DETECTION -> TRACKING mode with the largest contour found")
                except Exception as e:
                    last_bbox_in_subframe_coordinates = None
                    print(f"ERROR: Tracker init failed: {e}!!! Staying in DETECTING mode.")


        #
        # STATS
        #

        # Variable aggregation
        status_color = mode_colors.get(curr_mode, (255, 255, 255))
        meta_crossing = (last_crossing_time == curr_frame_time)

        # Time and FPS calculation
        frame_duration = curr_frame_time - prev_frame_time
        fps = 1.0 / frame_duration if frame_duration > 0 else 0.0

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



        #
        # IMAGE POST-PROCESSING (WHEN NEEDED)
        #

        if (meta_crossing or fps_temp_counter % STREAM_EVERY_X_FRAMES == 0):
            post_processing_queue.put_nowait((background.apply(curr_subframe_gray, learningRate=0),
                                              background.getBackgroundImage().copy(), 
                                              prev_frame.copy(),
                                              curr_frame.copy(),
                                              curr_frame_time,
                                              curr_subframe_gray.copy(),
                                              min_scaled_x,
                                              max_scaled_x,
                                              min_scaled_y,
                                              fps_string,
                                              status_color,
                                              meta_crossing,
                                              last_crossing_time,
                                              STREAM_EVERY_X_FRAMES > 1 and fps_temp_counter % STREAM_EVERY_X_FRAMES == 0))


        # ...and loop!
        prev_frame_time = curr_frame_time
        time.sleep(0.001)   # Avoid suffocating the CPU



#
# FRAME POST PROCESSING THREAD
#
def framePostProcessingWorker():
    while True:
        try:
            last_background_thresh, last_background_image, prev_frame, curr_frame, curr_frame_time, curr_subframe_gray, min_scaled_x, max_scaled_x, min_scaled_y, fps_string, status_color, meta_crossing, last_crossing_time, stream = post_processing_queue.get(block=True)

            # FRAME BEAUTIFICATION
            # Display FPS on the frame
            cv2.putText(curr_frame, f"{fps_string}", (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)

            # Display date and time
            cv2.putText(curr_frame, time.strftime("%Y/%m/%d %H:%M:%S"), (10, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, status_color, 2)

            # Flash on detection (but not on the same frame)
            if (not meta_crossing and last_crossing_time and abs(last_crossing_time - curr_frame_time) < CROSSING_FLASH_TIME):
                alpha = 1.0 - (abs(last_crossing_time - curr_frame_time) / CROSSING_FLASH_TIME)
                overlay = np.full_like(curr_frame, 255)  # White overlay
                cv2.addWeighted(overlay, alpha, curr_frame, 1 - alpha, 0, curr_frame)

            # Lines for the main frame
            cv2.line(prev_frame, (META_LINE_X_PX, int(FRAME_HEIGHT*MIN_Y_FACTOR)), (META_LINE_X_PX, int(FRAME_HEIGHT*MAX_Y_FACTOR)), (0, 255, 0), 2)
            cv2.line(curr_frame, (META_LINE_X_PX, int(FRAME_HEIGHT*MIN_Y_FACTOR)), (META_LINE_X_PX, int(FRAME_HEIGHT*MAX_Y_FACTOR)), (0, 255, 0), 2)
            cv2.line(curr_frame, (0, int(FRAME_HEIGHT*MIN_Y_FACTOR)), (FRAME_WIDTH, int(FRAME_HEIGHT*MIN_Y_FACTOR)), (0, 0, 255), 2)
            cv2.line(curr_frame, (0, int(FRAME_HEIGHT*MAX_Y_FACTOR)), (FRAME_WIDTH, int(FRAME_HEIGHT*MAX_Y_FACTOR)), (0, 0, 255), 2)
            cv2.line(curr_frame, (int(min_scaled_x/FRAME_SCALING), int(FRAME_HEIGHT*MIN_Y_FACTOR)), (int(min_scaled_x/FRAME_SCALING), int(FRAME_HEIGHT*MAX_Y_FACTOR)), (0, 0, 255), 2)
            cv2.line(curr_frame, (int(max_scaled_x/FRAME_SCALING), int(FRAME_HEIGHT*MIN_Y_FACTOR)), (int(max_scaled_x/FRAME_SCALING), int(FRAME_HEIGHT*MAX_Y_FACTOR)), (0, 0, 255), 2)

            # Bounding box for the main frame
            if last_bbox_in_subframe_coordinates:
                x_full_frame = int(last_bbox_in_subframe_coordinates[0]/FRAME_SCALING)
                y_full_frame = int((last_bbox_in_subframe_coordinates[1]+min_scaled_y)/FRAME_SCALING)
                w_full_frame = int(last_bbox_in_subframe_coordinates[2]/FRAME_SCALING)
                h_full_frame = int(last_bbox_in_subframe_coordinates[3]/FRAME_SCALING)
                cv2.rectangle(curr_frame, (x_full_frame, y_full_frame), (x_full_frame + w_full_frame, y_full_frame + h_full_frame), status_color, 2)
                cv2.putText(curr_frame, "Movida", (x_full_frame, y_full_frame - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1)


            # Build the edges image
            diff = cv2.absdiff(last_background_image, curr_subframe_gray)
            diff = cv2.GaussianBlur(diff, (5, 5), 0)
            edges = cv2.Canny(diff, 80, 180)


            # Right column stack with 1px line in between images and a 1px line meta line
            onepxline = np.full((1, last_background_image.shape[1]), 255, dtype=np.uint8)  # 1-pixel tall, full-width, grayscale
            stacked_images = np.vstack([
                last_background_image,
                onepxline,
                curr_subframe_gray,
                onepxline,
                last_background_thresh,
                onepxline,
                edges
            ])
            scaled_meta_line_x = int(META_LINE_X_PX * FRAME_SCALING)
            cv2.line(stacked_images, (scaled_meta_line_x, 0), (scaled_meta_line_x, stacked_images.shape[0]), (255, 255, 255), 1)


            # META CROSSING QUEUEING
            if meta_crossing:
                meta_crossing_queue.put_nowait((curr_frame_time, prev_frame.copy(), curr_frame.copy(), stacked_images.copy()))


            # STREAMING QUEUEING
    #       Theoritecally correct, but slower        
    #        try:
    #            frame_queue.put_nowait(frame.copy())
    #        except queue.Full:
    #            pass  # just skip, or log dropped frames
            if stream and not streaming_frame_queue.full():
#                streaming_frame_queue.put_nowait(curr_frame.copy())
                streaming_frame_queue.put_nowait(stacked_images.copy())

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(0.01)   # Avoid suffocating the CPU



#
# META PROCESSING THREAD
#
def processMetaCrossing():
    while True:
        try:
            meta_crossing_time, meta_crossing_prev, meta_crossing_frame, meta_crossing_stack = meta_crossing_queue.get(block=True)

            readable_time = time.strftime("%Y%m%d_%H%M%S", time.localtime(meta_crossing_time))
            print(f"META THREAD: Meta crossing at: {readable_time}")
            # cv2.imwrite(f"jpg/crossing_{readable_time}.jpg", meta_crossing_frame)

            _, jpg_byte_prev = cv2.imencode('.jpg', meta_crossing_prev)
            jpg_byte_prev = jpg_byte_prev.tobytes()
            _, jpg_byte_current = cv2.imencode('.jpg', meta_crossing_frame)
            jpg_byte_current = jpg_byte_current.tobytes()
            _, jpg_bytes_stack = cv2.imencode('.jpg', meta_crossing_stack)
            jpg_bytes_stack = jpg_bytes_stack.tobytes()

            pending_events_queue.put_nowait((meta_crossing_time, jpg_byte_prev, jpg_byte_current, jpg_bytes_stack)) 

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(0.1)   # Mostly unneeded, but just in case



#
# PUBLISHING EVENTS THREADS
#
def publishEvents():
    while True:
        try:
            meta_crossing_time, meta_crossing_prev_bytes, meta_crossing_frame_bytes, meta_crossing_stack_bytes = pending_events_queue.get(block=True)
            readable_time = time.strftime("%Y%m%d_%H%M%S", time.localtime(meta_crossing_time))
            print(f"EVENTS THREAD: Processing crossing at: {readable_time}")
        except Exception as e:
            print(f"Error: {e}")

        files = [
            ('image', ('a-frame.jpg', meta_crossing_prev_bytes, 'image/jpeg')),
            ('image', ('b-frame.jpg', meta_crossing_frame_bytes, 'image/jpeg')),
            ('image', ('b-stack.jpg', meta_crossing_stack_bytes, 'image/jpeg')),
        ]

        # Retry until success
        while True:
            try:
                response = requests.post(
                    "http://192.168.50.166:8080/lap/42",
                    data={"time": readable_time},
                    files=files,
                    timeout=5  # good to have a timeout to avoid hanging forever
                )
                response.raise_for_status()
                print("✅ Event posted successfully")
                break
            except requests.RequestException as e:
                print("❌ Error posting event:", e)

                # Optional: print response info if it exists
                if isinstance(e, requests.HTTPError) and e.response is not None:
                    print("🛠 Status code:", e.response.status_code)
                    print("📝 Body:", e.response.text)

                # Wait before retrying
                time.sleep(10)

        time.sleep(0.1)  # Mostly unneeded, but just in case



# === Flask Routes ===
def generate_stream():
    try:
        while True:
            try:
                output_frame_copy = streaming_frame_queue.get(timeout=3)
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
        line_x=META_LINE_X_PX,
        min_y=int(MIN_Y_FACTOR*100),
        max_y=int(MAX_Y_FACTOR*100),
        width=int(FRAME_WIDTH),
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

@app.route('/trigger_cooldown')
def trigger_cooldown():
    global trigger_cooldown
    trigger_cooldown = True
    return "Cool down triggered", 200

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
    global META_LINE_X_PX
    try:
        META_LINE_X_PX = int(request.args.get('x'))
        return f"Line X set to {META_LINE_X_PX}", 200
    except:
        return "Invalid value", 400

@app.route('/set_min_y')
def set_min_y():
    global MIN_Y_FACTOR
    global MAX_Y_FACTOR
    global trigger_cooldown
    try:
        y = float(request.args.get('y'))/100.0
        if y >= MAX_Y_FACTOR:
            return "Min Y must be less than Max Y", 400
        MIN_Y_FACTOR = y
        trigger_cooldown = True
        return f"Min Y set to {MIN_Y_FACTOR}", 200
    except:
        return "Invalid value", 400

@app.route('/set_max_y')
def set_max_y():
    global MIN_Y_FACTOR
    global MAX_Y_FACTOR
    global trigger_cooldown
    try:
        y = float(request.args.get('y'))/100.0
        if y <= MIN_Y_FACTOR:
            return "Max Y must be less than Min Y", 400
        MAX_Y_FACTOR = y
        trigger_cooldown = True
        return f"Max Y set to {MAX_Y_FACTOR}", 200
    except:
        return "Invalid value", 400

@app.route('/reset_autofocus')
def reset_autofocus_route():
    reset_autofocus()
    return "Autofocus reset", 200

# === Start Threads ===
if __name__ == '__main__':
    threading.Thread(target=capture_frames, daemon=True).start()
    threading.Thread(target=framePostProcessingWorker, daemon=True).start()
    threading.Thread(target=processMetaCrossing, daemon=True).start()
    threading.Thread(target=publishEvents, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, threaded=True)

import cv2
import numpy as np

from picamera2 import Picamera2


# Configuration
LINE_Y = 300         # Horizontal line position
TRACKER_TYPE = 'CSRT' # Options: CSRT, KCF, MOSSE
MIN_CONFIDENCE = 0.4  # Tracker confidence threshold
COOLDOWN_FRAMES = 15  # Prevent duplicate alerts

# Initialize
cv2.startWindowThread()

picam2 = Picamera2()
# picam2.configure(picam2.create_preview_configuration(main={"format": 'XRGB8888', "size": (640, 480)}))
picam2.configure(picam2.create_preview_configuration(main={"format": 'RGB888', "size": (640, 480)}))
picam2.start()

tracker = None
alert_active = False
cooldown = 0
crossing_history = []

# Try to detect available trackers
def get_available_trackers():
    trackers = {
        'CSRT': cv2.legacy.TrackerCSRT_create if hasattr(cv2.legacy, 'TrackerCSRT_create') else None,
        'KCF': cv2.legacy.TrackerKCF_create if hasattr(cv2.legacy, 'TrackerKCF_create') else None,
        'MOSSE': cv2.legacy.TrackerMOSSE_create if hasattr(cv2.legacy, 'TrackerMOSSE_create') else None,
        'GOTURN': cv2.TrackerGOTURN_create if hasattr(cv2, 'TrackerGOTURN_create') else None
    }
    return {name: create for name, create in trackers.items() if create}

# Use first available tracker from the priority list
AVAILABLE_TRACKERS = get_available_trackers()
TRACKER_TYPE = list(AVAILABLE_TRACKERS.keys())[0]  # Auto-select first available
print(f"INFO: Using tracker: {TRACKER_TYPE}")

def init_tracker(frame, bbox):
    create_func = AVAILABLE_TRACKERS[TRACKER_TYPE]
    tracker = create_func()
    tracker.init(frame, bbox)
    return tracker

while True:
    frame = picam2.capture_array()
    # print("DEBUG: Frame shape:", frame.shape)

    # Cooldown counter
    if cooldown > 0:
        cooldown -= 1

    # Detection and tracking logic
    success = False
    if tracker is not None:
        # Update tracker
        success, bbox = tracker.update(frame)
        if success:
            # Get bounding box coordinates
            x, y, w, h = [int(v) for v in bbox]
            center_y = y + h//2

            # Check line crossing (using bounding box edges)
            top_cross = y <= LINE_Y <= y + h
            bottom_cross = (y + h) >= LINE_Y >= y
            direction = "DOWN" if center_y > LINE_Y else "UP"

            # Check for valid crossing
            if (top_cross or bottom_cross) and cooldown == 0:
                # Verify crossing consistency
                crossing_history.append(direction)
                if len(crossing_history) > 5:
                    crossing_history.pop(0)
                
                # Trigger alert if consistent direction
                if len(set(crossing_history)) == 1:
                    alert_active = True
                    cooldown = COOLDOWN_FRAMES
                    print(f"ALERT: Object crossed line moving {direction}")
        else:
            # Lost tracking, reset
            tracker = None

    else:
        # Detect new objects using simple motion detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        if not hasattr(init_tracker, 'avg'):
            init_tracker.avg = gray.copy().astype("float")
        
        # Accumulate weighted average
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

    # Visuals
    cv2.line(frame, (0, LINE_Y), (frame.shape[1], LINE_Y), (0, 255, 0), 2)
    if tracker is not None and success:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
    if alert_active:
        cv2.putText(frame, "CROSSING DETECTED", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        alert_active = False

    cv2.imshow("Fast Object Tracking", frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cv2.destroyAllWindows()
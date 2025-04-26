# se-lapdetector
Lap detector for Slotem Extremus

Pending features:
* Buffer of events to Go server with frame

Little improvements:
* Line_X as a percentage
* Use nanotime from capturerequest instead of system time
* Prepare the frame to render only when broadcasting

Big improvements:
* Precise crossing line:
  * Use canny around detection for precise crossing line?
  * Evaluate the shadows over the meta line?
* When tracking, do it only within a ROI for efficiency. Two parameters are needed: horizontal jump and vertical jump.
* Stream more than one image?
* Motion history: consider doing it weighted
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows. Video can be smoother, but remember that libcamera2 graciously adapts the frame rate for us when dropping...
* There's a tail now when objects are large, maybe because of the motion history? But motion history reduces false positives...
* Make daemon=false in threading.Thread(target=processMetaCrossing, daemon=True).start()


Day dreaming:
* Use YOLO to actually track cars


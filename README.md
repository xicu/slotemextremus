# se-lapdetector
Lap detector for Slotem Extremus

Pending features:
* Buffer of events to Go server with frame

Little improvements:
* Line_X as a percentage
* Minimum contour area as percentage
* Show timestamps
* Use nanotime from capturerequest instead of system time
* Show vertical lines with width threshold

Big improvements:
* Motion history: consider doing it weighted
* Try cv2.createBackgroundSubtractorMOG2 instead of manual background substraction
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows. Video can be smoother, but remember that libcamera2 graciously adapts the frame rate for us when dropping...
* Better substract the background (there's a tail now when objects are large, maybe because of the motion history? But motion history reduces false positives...)

Day dreaming:
* Use YOLO to actually track cars


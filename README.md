# se-lapdetector
Lap detector for Slotem Extremus

Pending features:
* Buffer of events to Go server with frame

Little improvements:
* Save contour instead of bounding box for last know position
* Better line_x cross detection
* Line_X as a percentage
* Use nanotime from capturerequest instead of system time

Big improvements:
* Start tracking only after far from the frame
* Try cv2.createBackgroundSubtractorMOG2 instead of the manual motion history
* Load the motion history while in cooldown
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows

Day dreaming:
* Use YOLO to actually track cars


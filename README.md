# se-lapdetector
Lap detector for Slotem Extremus

Pending features:
* Buffer of events to Go server with frame

Little improvements:
* Line_X as a percentage
* Minimum contour area as percentage
* Show timestamps
* Use nanotime from capturerequest instead of system time

Big improvements:
* Start tracking only after far from the frame
* Try cv2.createBackgroundSubtractorMOG2 instead of the manual motion history
* Load the motion history while in cooldown
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows
* Better substract the background (there's a tail now when objects are large, maybe because of the motion history? But motion history reduces false positives...)

Day dreaming:
* Use YOLO to actually track cars


# se-lapdetector
Lap detector for Slotem Extremus

Pending features:
* Buffer of events to Go server with frame

Little improvements:
* Revert the width threshold: instead of measuring the percentage from one side to the other, do the percentage from the meta line to the sides.
* Line_X as a percentage
* Show timestamps
* Use nanotime from capturerequest instead of system time
* Show vertical lines with width threshold
* Show size in percentage instead of Movida
* Prepare the frame to render only when broadcasting

Big improvements:
* Fix the parallax problem when crossing the meta: when the car is on one side and the tracking starts, the front of the car is visible. However, as the car moves towards the center, the front is not disappears but the bounding box allocates space for it. As a consequence, the bounding box is always ahead of the car. There are many solutions to this problem, including just evaluating the meta line when the car gets closer, or tracking only when the car is very close to the center of the image.
* Stream a combination of four images instead of one: original, gray, background, contours
* Motion history: consider doing it weighted
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows. Video can be smoother, but remember that libcamera2 graciously adapts the frame rate for us when dropping...
* There's a tail now when objects are large, maybe because of the motion history? But motion history reduces false positives...
* Make daemon=false in threading.Thread(target=processMetaCrossing, daemon=True).start()


Day dreaming:
* Use YOLO to actually track cars


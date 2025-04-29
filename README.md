# se-lapdetector
Lap detector for Slotem Extremus

Bugs:
* STREAM_SCALING is not used

Little improvements:
* Meta crossed flag up on crossing and down on cool_down
* Line_X as a percentage
* Use nanotime from capturerequest instead of system time

Big improvements:
* Event retry should be different depending on what:
  * Very fast for metadata
  * Quite slow for images
* Metadata and images should fly in different pipelines (and we shouldn't try images before succeeding with metadata)
* Precise crossing line:
  * Use canny around detection for precise crossing line?
  * Evaluate the shadows over the meta line?
* When tracking, do it only within a ROI for efficiency. Two parameters are needed: horizontal jump and vertical jump.
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows. Video can be smoother, but remember that libcamera2 graciously adapts the frame rate for us when dropping...
* Adjust the whole background thing. We spent a lot of time on this and it happened to be an issue with the autoexposure!

Day dreaming:
* Use YOLO to actually track cars


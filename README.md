# se-lapdetector
Lap detector for Slotem Extremus

Bugs:
* STREAM_SCALING is not used
* Clean                 # Detect a potential crossing of the line

Little improvements:
* Line_X as a percentage
* Use nanotime from capturerequest instead of system time

Big improvements:
* Show two streamings (real frame, processed images)
* Support disable streaming
* Event retry should be different depending on what:
  * Very fast for metadata
  * Quite slow for images
* Metadata and images should fly in different pipelines (and we shouldn't try images before succeeding with metadata)
* When tracking, do it only within a ROI for efficiency. Two parameters are needed: horizontal jump and vertical jump.
* Detect & track to a different thread, queue to communicate, and skip frames when queue grows. Video can be smoother, but remember that libcamera2 graciously adapts the frame rate for us when dropping...
* What about a pre-emptive contour detection? Like 2 frames at the same time. Worst case scenario, one frame has to be discarded when tracking initiates...
* Adjust the whole background thing. We spent a lot of time on this and it happened to be an issue with the autoexposure!
* Support the scenario when a car jumps the meta (ie. canny never overlaps the line)
* Acurate timing of meta crossing (we would need to interpolate between pre and post-meta)

Day dreaming:
* Use YOLO to actually track cars


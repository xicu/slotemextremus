# se-lapdetector
Lap detector for Slotem Extremus

Bugs:
* STREAM_SCALING is not used
* Clean                 # Detect a potential crossing of the line

Little improvements:
* Line_X as a percentage
* Use nanotime from capturerequest instead of system time
* Show two streamings (real frame, processed images)
* Support disable streaming

Big improvements:
* Keep a circular queue of frames and create a total of three threads/processes:
  * First process to capture all the frames, resize them, split them, and put them in the queue
  * Second thread to detect and track, considering that:
    * If we're detecting or tracking, we can get the latest frame
    * If we're very close to the meta, then we get the next frame
  * Third frame to process the events (streaming, meta crossing, and even video creation once we have the frames queue).
* Event retry should be different depending on what:
  * Very fast for metadata
  * Quite slow for images
* Metadata and images should fly in different pipelines (and we shouldn't try images before succeeding with metadata)
* When tracking, do it only within a ROI for efficiency. Two parameters are needed: horizontal jump and vertical jump.
* What about a pre-emptive contour detection? Like 2 frames at the same time. Worst case scenario, one frame has to be discarded when tracking initiates...
* Adjust the whole background thing. We spent a lot of time on this and it happened to be an issue with the autoexposure!
* Support the scenario when a car jumps the meta (ie. canny never overlaps the line)
* Acurate timing of meta crossing (we would need to interpolate between pre and post-meta)

Day dreaming:
* Use YOLO to actually track cars


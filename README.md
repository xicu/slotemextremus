# Raspberry Pi Lap Detector for Slotem Extremus

Welcome to the camera-based lap detector component of the Slotem Extremus project!

## Definition and Scope
This component uses a camera connected to a Raspberry Pi to detect when a slot car crosses a meta line. When that happens, it sends an HTTP event to another server with the details, including the photo finish.

## Requirements
To enjoy this piece of software, you'll need:
* A **Raspberry Pi 4** (although it should also work on a 3, and aim to make it work even on a Zero 2 when ported to C++) using a regular Raspberry Pi OS (Lite should be enough, and even recommended).
* A **Raspberry Pi Camera Module 3**. In theory, any other camera compatible with the PiCamera2 library should work, and with very little effort it should also work with any camera supported by OpenCV.

## Status of the Project
I consider that this is an MVP (_Minimum Viable Product_) because:
* **It does the job**. Actually, it works better than I ever expected even for a final product. It does all I wanted (it detects cars very well and it sends the events to another server) and it's stable (running for hours with no issues).
* **It has a very good number of configuration possibilities**, some of them offered via an integrated web server, some of them offered through simple parameter edition.
* **It performs very well** (30+ FPS average when capturing at 720p and with real-time streaming enabled).
* **The code is bad**. Really bad, seriously. It's just a prototype that happened to grow. Also, it's hitting the Python limits in terms of performance (specifically, in terms of concurrency capabilities).

Rather than refactoring its Python code, I aim to rewrite it in C++. The reason is that Python will anyways limit me in terms of performance, whereas with C++ the sky will be the limit.

However, I don't want to blame Python here (even though I have a microtrauma because it fooled me with its fake threading capabilities). After all, Python allowed me to prototype and to try out new things super easily.


## But... why?
Well... why not? The history began around 2008, when some friends and I were missing a good..dfsafdfsdfsf

## How does it work?
opencv, background, detection, tracking, edge contour over the meta line

## Why all that effort? Why not just the edge contour over the meta line?

## What challenges did you find?


## What about the future?
hobby, learning, c++


## TO-DO (or _ideas_) list

### Bugs
* STREAM_SCALING is not used

### Little improvements
* Line_X as a percentage
* Use nanotime from capturerequest instead of system time
* Show two streamings (real frame, processed images)
* Support disable streaming

### Big improvements
* Keep a circular queue of frames and create a total of three threads/processes (but this will have to wait to the C++ port, as the multithreading/processing in Python is quite poor):
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

### Day dreaming
* Use YOLO to actually track cars


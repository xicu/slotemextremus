# Raspberry Pi Lap Detector for Slotem Extremus

Welcome to the camera-based lap detector component of the **Slotem Extremus** project!


## Definition and Scope

This component uses a camera connected to a Raspberry Pi to detect when a slot car crosses a meta line. When that happens, it sends an HTTP event to another server with the details, including the photo finish.

![No matter what the question is - LEGO is the answer](assets/images/lego.jpg "3D printers are overrated")

The camera is expected to be perpendicular to the track. It doesn't matter if it's at ground level or in a zenital view. This is how it looks when it detected me crossing the line in my car:

![Me driving by!](assets/images/20250501_171326.525_b-frame.jpg "My beloved MINI and I")


## Requirements

To enjoy this piece of software, you'll need:
* A **Raspberry Pi 4** (although it should also work on a 3 with enough FPS, and I aim to make it work even on a Zero 2 when ported to C++) using a regular Raspberry Pi OS (Lite should be enough, and even recommended).
* A **Raspberry Pi Camera Module 3**. In theory, any other camera compatible with the PiCamera2 library should work, and with very little effort it should also work with any camera supported by OpenCV. I tend to use percentages rather than absolute pixel counts, and times rather than frames in order to keep all the logic compatible with different combination of resolution and FPS.


## Status of the Project

I consider that this is an MVP (_Minimum Viable Product_) because:
* **It does the job**. Actually, it works better than I ever expected even for a final product. It does all I wanted (it detects cars very well and it sends the events to a server) and it's stable (running for hours with no issues).
* **It has a very good number of configuration possibilities**, some of them offered via an integrated web server, some of them available through simple parameter edition.
* **It performs very well**: 30+ FPS average when capturing at 720p and with real-time streaming enabled.
* **It monitors the system**: CPU usage, RAM pressure and CPU temperature are seen real-time.
* **The code is bad**. Really bad, seriously. It's just a prototype that happened to grow. Also, it's hitting the Python limits in terms of performance (specifically, in terms of concurrency capabilities).

Rather than refactoring its Python code to make it production quality, I aim to rewrite it in C++. The reason is that Python will anyways limit me in terms of performance, whereas with C++ the sky will be the limit. I don't want to blame Python here though (even when I have a microtrauma because it fooled me with its fake threads). After all, Python allowed me to prototype and to try out new things super easily.


## But... why?

Well... why not? You can find an introduction to the project in the [master README file](/slotemextremus/README.md), so let's focus on this component. In brief, instead of a fully featured PC and a webcam (as planned in 2008), I wanted to get a Pi a chance because:
* Everybody has one at home.
* It would be cool to have a completely wireless device (when on batteries) monitoring the laps.
* And also because it sounds challenging, to be honest.
* I needed some sort of completitude feeling (that thing was in my TO-DO for too long).


## How does it work?

I could nerd a lot about this, because I enjoyed it to the fullest. I will keep it very simple (mostly for my future me, because I tend to forget things easily):

1. You capture frames at a fast pace with the Picamera2 library. Since all the process that follows will be exhausting for the CPU, you scale those frames down with OpenCV (you don't capture them in lo-res because you want the hi-res for the photo finish, of course) and you convert them to grayscale. You also trim according to some threasholds and so (there's no point in waisting CPU time detecting movement out of the track).

1. You need a background. Yeah, basically you need a reference against which you evaluate if there are changes (ie. cars passing by). I made it self-calibrating by the way.

1. You need to detect changes compared to that background. Specifically, OpenCV will find contours. What you do is to filter them out and act only on those bigger than certain threshold. This and the next step are those requiring the most resources of the Pi.

1. When you get a good contour, you try to track it. OpenCV has tools for this as well, and you have to choose them wisely. There're big differences in performance depending on the track you use, and depending on the area you track. Fine tuning the background building, the contour detection and the tracking, as well as building heuristics to reduce the load on your CPU, are an art in itself.

1. When tracking, you check whether the object leaves the frame, or whether it crosses the meta. To understand whether the car is crossing the meta, you check the difference between the frame and the background in the meta area, as the bounding box of the tracker is always bigger than the car (more on this on _the parallax problem_). When the difference goes beyond certain threshold, you trigger the appropriate event. The most reliable and accurate (to the pixel) way to do this is to actually use canny edge detection on the delta between the frame and the background. If the found edges are over the meta line, then you have a lap.

1. You stream everything - that's the only proper way to understand what's going on with your system. You of course do this in a different thread, as the main loop is already super heavy and can't hold any more load (unless you want to see your FPS dropping...).

1. You need some configuration to happen real-time, so there's a tiny embedded web server to move the meta line and a couple of thresholds.

There are quite some heuristics to get things optimized inthe limited resources of the Pi. Just to name a few:
* Frames are captured at a nice resolution to have cool photo finishes, but the processing happens with a grayscale and low resolution version of those.
* I don't stream all the frames but a one every three or four (streaming means converting to jpeg, besides the streaming overhead itself).
* I have some vertical bands to ensure that I don't process the pixels that are above or beyond the road, etc.


## Why do you need to detect and track contours? Why not just the edge contour over the meta line?

Dunno what ur talking bout...


## You say that the meta crossing is done with canny detection, and motion detection plus tracking are so heavy for the Pi. Why don't you just focus on the actual meta crossing?

N/A


## But seriously...

OK, OK, OK. It's just overengineering as a consequence of not thinking upfront. Period.

Just basic edge detection over the meta could run even on a first generation Pi, or at least in a Pi 2 (the first multicore). I didn't do it as a first option because... I didn't think of it. I was just too narrow minded and only saw motion detection and tracking as an option. Looking backwards, it would have saved me many, many hours of coding and testing and optimizations.

Despite being _don't trust your GenAI companion at first - they also tend to overengineer_ a big finding (those LLM tend to tell you what you want to hear), I also got a very good amount of technical learnings with this detour, namely:
* A very interesting foundation to computer vision. This has been in my to-do for longer than this project, actually, and it's done now.
* Finding out that multi-threading is not always _multi-threading_ when you leave the beautiful C++ world.
* Building the foundation for other hobby projects, yay!

Also, the current setup reduces the chances of false positives virtually to zero (I only check for meta crossing when tracking an object very close to the actual meta). Whether I would have implemented motion detection and tracking to reduce the false positives, we'll never know...


## What challenges did you find?

### CPU Throttling

I started the prototype with a naked Raspberry. Sometimes, the streaming was not good, but you can't know what the reason is. It could be:
* Wrong logic, like detecting too many contours because the background is polluted.
* Network issues.
* Race conditions or other problems with your threads, etc.

I found that the Pi 4 needs cooling for these activities, yes. I learnt that the CPU can go down from 1.5 GHz to 600 MHz when the temperature reaches 85 degrees. And I learnt it the hard way: by experimenting.

Ultimately, I learnt that monitoring and observability are a must, even for a tiny project like this. Why? Because despite being the CPU throttling my main performance issue, I actually had more (like thread starvation), and I was overlooking them until I solved the temperature problem (with a large passive aluminium heatsink).

In brief, whenever you are going to work on a high-demanding project (yeah, this is high-demanding for the hardware we're using), be sure that you have the right tools to monitor what's going on.

 ![System information that is shown in the embedded web server](assets/images/systemstatus.png)

### Multi-threading

TLDR multi-threading in Python is a joke, and I only found it the hard way, when splitting the execution logic across different threads didn't scale as expected.

Coming from C++, I expect threads to be concurrent execution lines within my process, all of them sharing the same memory space. That's not the case in Python. In Python, they are not concurrent - period. There're workarounds that might or might not work. I explored them and I found myself putting a square peg in a round hole. That's when I decided to accept this as a very nice MVP and use real multithreading in C++ in the future.

I'm skipping the obvious: why do we need multi-threading in this app? It's just because there're many things going on at the same time, plus multi-core CPUs are an standard nowadays and it's a waste to not use them (the Pi has 4 cores since the 2nd generation, for instance). Unfortunately, Python will not use those extra cores because its threads are not OS threads.

### The parallax problem

When tracking an object, OpenCV will give you its bounding box. As long as the meta line is perpendicular to either the X or the Y axis, checking the overlapping between the bounding box and the meta line would be a good way to understand when a car is crossing.

That's what I thought, and I was wrong. I couldn't understand why the bounding boxes were crossing the meta line way earlier than the actual cars were touching the meta line. You can see that in the picture at the top. And it was not a matter of some specific offset that I could compensate: it was random. The clue was that the problem didn't exist when tracking bikes instead of cars. Why that?

The problem was always in front of my eyes, but it took me quite some time to get it: when a car comes by one side of the frame, you see both the front of the car and its side, and you start tracking the whole thing. As it gets to the center of your frame (typically where the meta line is), you only see the side because the front gets hidden in the new perspective. However, the tracker still expects the front to be there and even to show up again, so it gives you a bounding box with allocated room for that (now hidden) front of the car. And because of that, your bounding box is actually ahead of the car when it crosses the line. Bikes didn't show this problem because they have virtually no depth (ie. no _front_)

This would still be enough to count laps, honestly. However, I always wanted to have a photo finish of my laps, so I ended up with an extra step in my detection logic: when the bounding box was crossing the meta line, I added some canny edge detection to check if the car was actually touching the meta line at the pixel level.

 ![Images that are used internally](assets/images/20250501_171326.525_b-stack.jpg "Background, current frame, contours, and edges")

Overengineered? Maybe, but it was fun, challenging and insightful, so I'm happy I did it.

### The auto-exposure complication

Sometimes, the trackers fail. You never know whether it is because the object dissapeared, or whatever. What you do is to fall back to detect contours again.

One thing that used to happen very often was that when the cars were very large (typically, vans), the tracker would fail and the contour detection would struggle to stay above 10 FPS. Why that? I had no idea...

I started to stream not the real video but the internal images instead. I noticed that sometimes the detected contours were not just around the cars or the vans, but everywhere, so the contour processing logic was processing dozens of wrong contours. It was like the background was broken when large cars were in the frame, and I couldn't get why.

It didn't make sense, and I was lost for a lot of time until, out of the blue, I found the reason: when a large object came into the frame, chances were that the whole image would be either lighter or darker, and the camera auto-exposure was making the image either darker or lighter to compensate. When the image was all of a sudden either lighter or darker, the contour detection was finding deltas compared to the background everywhere! And chaos happened.

The fix was simple: I now lock the exposure when the tracking of a car begins, and I re-enable it when the car leaves the frame. So easy to explain, so easy to fix, so difficult to spot...


## What about the future?

This is nothing but a hobby projects to learn and have fun. That's all about it.

The question, then, is _what do I want to learn next?_. The answers:
* I want to code C++ again. It's fast, it's hardcore, it's almost old school... and I miss it, plus I need it to overcome the limitations of the Pi's hardware. Yes, I could just get a faster Pi, or a faster mini computer; but:
  * Then I wouldn't be learning, plus...
  * I truly believe that if your first solution to performance problems is to have new hardware, you're not a good engineer, plus...
  * The fun is in it being challenging!
* I want to change the underlying logic, with a circular queue of frames with the following workers acting on it:
  * A frame provider, which will take care of capturing the frame and doing the basic corrections (resizing, grayscale, thresholding, frame splitting, etc).
  * A motion detector+tracker, which will take care of the heavy logic. I want it to be smart enough to skip some frames if the collection is building faster than I'm processing them (and we're not too close to the meta). As contour detection is usually the bottleneck, I could even do pre-emptive contour detection (ie. two frames being processed at the same time, with the _future_ frame just being discarded once that a contour is detected).
  * A post-processor, which will either ignore the frames in the queue or send them to the meta processor (when that's the case) or to the streamer (when needed). The meta processor will be able to fetch previous frames from the queue (ie. it will enable the _video finish_).
* I will detect two lanes. I don't do it know because I don't have the setup to test it (yup, you see that I'm testing it with real cars from the window of Lena & Xana). However, I've decided to wait for this split until I have real threads, which will happen when I have the port to C++ done (which will happen when the other Slotem Extremus components are MVP as well). With the logic depicted above, it will be as easy as making an extra image split on frame acquisition and spawning an extra thread.
* I want to give YOLO and so a try. I could have added an AI hat from the beginning to the Pi, or I could have used the existing AI camera, but then [_put the reasons above about learning and having fun here_]. Now that things are working, I feel that adding AI (for instance, to detect the model of the car) would be awesome.


## TO-DO/Ideas list

Below there's a mix of ideas, bugs, and random notes to use as inspiration in the future.

### Bugs

* STREAM_SCALING is not used (and probably more variables as well...)

### Little improvements

* Line_X as a percentage
* Use nanotime from capturerequest instead of system time
* Support disable streaming

### Bigger improvements

* Metadata and images should fly in different pipelines (and we shouldn't try images before succeeding with metadata):
  * It has to be very fast for metadata, so the lap events go fast to the backend and are propagated quickly
  * It can be slower for images, as we can wait a couple of seconds to view the pictures
* Choose left to right, right to left, or both trackings (when only one side, countour detection will happen only on one side of the meta). Now it's both.
* When tracking, do it only within a ROI for efficiency. Two parameters are needed: horizontal jump and vertical jump. That way, the tracking algorithm won't be that heavy on the CPU.
* Adjust the whole background thing. We spent a lot of time on this and it happened to be an issue with the autoexposure! Now it's time to readjust it, and maybe to make it lighter (with less history) as well.
* Support the scenario when a car jumps the meta (ie. canny never overlaps the line).
* Acurate timing of meta crossing (we would need to interpolate between pre and post-meta images - now we get the time from the post).

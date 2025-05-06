# Slotem Extremus

Welcome to the magnificent, useless, and super fun to build **Slotem Extremus** project!

One day I'll use this to track slot cars laps and races with Lena & Xana. In the meanwhile, I'm just having fun :D

## What is this about?

As any boy in the 80's, I loved my [Scalextric](https://www.scalextric.es). Around 2008, I went back to the hobby with a couple of friends.

![This was in 2009](assets/images/IMG_1527.JPG "This was in 2009")

It was in no time that things went a bit out of control...

![Just a little track in 2010...](assets/images/IMG_20101227_172034.jpg "Just a little track in 2010...")

Besides building ridiculously large tracks, we all understood the need for a better way to monitor our laps and manage our races. All we had, was an old .exe running on Windows 95 and using the parallel port to read a couple of sensors (photocells drilled under a piece of track). The setup was outdated already back then.

![Windows 95 powered](assets/images/IMG_1525.JPG "Windows 95 powered")

Back in 2009, I wanted to make it with a native app and computer vision (with OpenCV). 2^8 years later, I made it happen with a Raspberry Pi (more on this in the [README of the lapdetector](lapdetector/README.md)).


## Why now?

It's a combination of factors, namely:

* As a frustrated game developer who became a C++ engineer and who later took the managereal path, I found the need to find my roots (ie. to code again).
* The industry trend is now expecting managers to be either hands-on or very close to the code, and I just got too dettached from tech. The industry is now also laying people off, and I don't want to wait for it whining in a corner. And I only learn by doing.
* I wanted to try these AI agents first hand. I didn't want to screw our production code, but I also wanted to do more than renaming labels or adding new buttons. A hobby project was the solution.
* Lena & Xana. I wanted to play slot cars with them when they turn 6, in Septermber 2026 (it happens that this will be ready way earlier though :D). I don't want them to play to _girls_ games but to any game, and we want us to do it together. In the end, it's all about them.

![Don't mess with them](assets/images/CFF414D3-C665-47ED-A4BC-44CEEF3F34AA-4353-0000035EF8016FD6.jpeg "Don't mess with them")


## What's the status of the project?

Minimum Viable Skeleton, I would say.

Things that are done:
* This repo is set.
* The high-level architecture is clear.
* Platforms and hardware constrains are either identified or set.
* All the foreseen components have been proven to be feasible, and are actually interacting with each other.
* There's an MVP of the lap detector (argubly, the most challenging component).

Thigs that are pending:
* A real backend, including its data model, its endpoints, its business logic and its storage solution.
* A real frontend, including a nice UX that allows me to eventually enjoy the races.


## How does it work?

3 components bc learning, brief explanation, interaction, links to the subfolders


## Thoughts on AI?

Very, very positive. Having a companion that will solve your problems (quite often) is priceless. This hobby project wouldn't have been be a working skeleton in only two months without these new tools.

However, I'm also getting a bunch of good learnings while doing this...

### Your AI agent tries to please you

The better the prompt, the better the output. The problem is that we humans will implicitely share our intent when sharing details of our request, and the AI is a bad friend who rarely challenges you, but enforces you instead.

### Your AI agent is more narrow-minded than you wish

See all the unneeded? work on the motion detection and tracking in the lap detector component for more details.

### Your AI agent will hide critical aspects of the solutions

I knew that my lap detector had to be multi-threaded. The AI agent confirmed it. It never told me that Python threads are a scam :/

### The code is crap

I'm sorry, but it's like that. There's no linter or AI that can fix the code of an AI.


## What's next?

I have absolutely no idea.

The amount of possible optimizations in the lap detector is huge, and so is the possibilities to build a user friendly UI. I could even extend the data model in the backend to support partial times, like in F1. Or I could use some LLM to identify the car model. Or to track more than one car in the same lane at the same time. I'm also tempted to make this more efficient (I would love to see it running on a battery powered Raspberry Pi Zero, which has like half the CPU power and 1/8th of the RAM of my current Pi 4). 

Honestly, I don't know what's going to be next. In the end, it's all about enjoying the journey... and the races with Lena & Xana <3
---
title: paper2video
emoji: 🎬
colorFrom: indigo
colorTo: yellow
sdk: gradio
sdk_version: 5.0.0
app_file: app.py
pinned: true
license: apache-2.0
short_description: Any article → 3Blue1Brown-style explainer video
tags:
  - manim
  - tts
  - video-generation
  - explainer
  - education
  - claude
---

# paper2video

Turn any technical article into a 2–5 minute narrated 3Blue1Brown-style explainer video.

Paste a URL → wait 3-5 minutes → get a video with Manim animations and Kokoro TTS narration.

**Stack:** Claude (script + Manim codegen) · Manim CE (animation) · Kokoro 82M (voice) · ffmpeg

[GitHub](https://github.com/edwardyen724-g/paper2video) · Apache 2.0

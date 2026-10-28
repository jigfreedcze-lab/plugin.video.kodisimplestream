# -*- coding: utf-8 -*-
"""Video preview: the frames of the Webshare preview stripe shown one by one in a window."""

from __future__ import annotations

import io
import os
import threading
from typing import List

FRAME_SECONDS = 1.0
DOWNLOAD_TIMEOUT = (3.05, 10)
# Actions that close the window – not every action, mouse moves would close it at once
CLOSE_ACTIONS = {7, 9, 10, 13, 92, 100, 101, 122}  # select, parent dir, menu, stop, back, mouse clicks


def split_stripe(data: bytes, count: int, folder: str) -> List[str]:
    """Cuts the stripe (frames side by side in one JPEG) into separate files, returns their paths."""
    from PIL import Image  # script.module.pil, imported only when a preview is requested

    strip = Image.open(io.BytesIO(data)).convert("RGB")
    if count <= 0:
        # Webshare frames are 16:9
        count = max(1, round(strip.width / (strip.height * 16 / 9)))
    width = strip.width // count
    os.makedirs(folder, exist_ok=True)
    paths = []
    for index in range(count):
        path = os.path.join(folder, f"{index}.jpg")
        strip.crop((index * width, 0, (index + 1) * width, strip.height)).save(path, quality=90)
        paths.append(path)
    return paths


def load_frames(stripe_url: str, count: int, folder: str) -> List[str]:
    """Frames from the cache folder, or downloaded and cut on the first request."""
    if count > 0:
        cached = [os.path.join(folder, f"{index}.jpg") for index in range(count)]
        if all(os.path.isfile(path) for path in cached):
            return cached
    import requests

    response = requests.get(stripe_url, timeout=DOWNLOAD_TIMEOUT)
    response.raise_for_status()
    return split_stripe(response.content, count, folder)


def show(frames: List[str], title: str, background: str) -> None:
    """Shows the frames in a modal window, one per FRAME_SECONDS, until the user closes it."""
    import xbmc
    import xbmcgui

    class PreviewWindow(xbmcgui.WindowDialog):
        def __init__(self):
            super().__init__()
            self.stopped = False
            # Window coordinates are 1280x720 regardless of the screen resolution
            self.addControl(xbmcgui.ControlImage(0, 0, 1280, 720, background, colorDiffuse="E6000000"))
            self.image = xbmcgui.ControlImage(160, 60, 960, 540, frames[0], aspectRatio=2)
            self.addControl(self.image)
            self.label = xbmcgui.ControlLabel(160, 620, 960, 40, "", alignment=0x00000002)
            self.addControl(self.label)

        def onAction(self, action):
            if action.getId() in CLOSE_ACTIONS:
                self.stopped = True
                self.close()

        def cycle(self):
            monitor = xbmc.Monitor()
            index = 0
            while not self.stopped:
                self.image.setImage(frames[index], False)
                self.label.setLabel(f"{title}  [{index + 1}/{len(frames)}]")
                index = (index + 1) % len(frames)
                if monitor.waitForAbort(FRAME_SECONDS):
                    self.stopped = True
                    self.close()

    window = PreviewWindow()
    thread = threading.Thread(target=window.cycle, daemon=True)
    thread.start()
    window.doModal()
    window.stopped = True
    thread.join(FRAME_SECONDS * 2)
    del window

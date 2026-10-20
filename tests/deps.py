"""Skip tests whose optional dependencies are missing instead of reporting them as failures."""

import importlib.util
import unittest

needs_jsonschema = unittest.skipUnless(importlib.util.find_spec("jsonschema"), "jsonschema is not installed")
needs_pillow = unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
needs_fast = unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("cv2"),
                                 "numpy and OpenCV (opencv-python-headless) are not installed")

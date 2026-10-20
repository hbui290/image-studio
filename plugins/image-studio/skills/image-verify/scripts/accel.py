"""Optional numpy + OpenCV acceleration for the image-verify scripts.

Pillow stays the only required image library. When numpy and OpenCV (opencv-python-headless) are both importable,
the accelerated commands may use them; every accelerated path has a pure-Pillow fallback that gives the same
pass/fail verdict. Choose with --engine auto|pillow|fast or IMAGE_STUDIO_ENGINE=pillow|fast (the flag wins):
auto uses numpy/OpenCV when both import, pillow never does, fast requires them (bad input, exit 2, without them).
"""

import os

ENGINES = ("auto", "pillow", "fast")
ENV = "IMAGE_STUDIO_ENGINE"
NUMPY_PIN = "numpy==2.0.2"
OPENCV_PIN = "opencv-python-headless==4.11.0.86"
INSTALL_HINT = (f"uv run --with pillow --with jsonschema --with {NUMPY_PIN} --with {OPENCV_PIN} python3 ... "
                f"(or pip install {NUMPY_PIN} {OPENCV_PIN})")

_modules = None
_active = False  # True after select() chose numpy/OpenCV


def modules():
    """(numpy, cv2) when both import, else (None, None). Imported once, only when first asked."""
    global _modules
    if _modules is None:
        try:
            import numpy
            import cv2
            _modules = (numpy, cv2)
        except Exception:  # ImportError, or a broken binary wheel
            _modules = (None, None)
    return _modules


def available():
    return modules()[0] is not None


def select(flag=None):
    """Pick the engine from --engine (flag) or IMAGE_STUDIO_ENGINE; returns "fast" or "pillow".

    Raises ValueError with a message for an unknown name or for fast without numpy/OpenCV."""
    global _active
    choice = (flag or (os.environ.get(ENV) or "").strip() or "auto").strip().lower()  # blank variable = unset
    if choice not in ENGINES:
        source = "--engine" if flag else ENV
        raise ValueError(f"{source} must be auto, pillow or fast, got {choice!r}")
    if choice == "pillow":
        _active = False
    elif available():
        _active = True
    elif choice == "fast":
        raise ValueError(f"engine fast needs numpy and OpenCV: {INSTALL_HINT}")
    else:
        _active = False
    return "fast" if _active else "pillow"


def reset():
    """Back to Pillow; commands without an engine choice always run on Pillow."""
    global _active
    _active = False


def fast():
    """True when the current command selected numpy/OpenCV."""
    return _active


def label():
    return "numpy/opencv" if _active else "pillow"


def to_array(img):
    """PIL image to a numpy array (uint8; L gives HxW, RGB/RGBA give HxWxC)."""
    np = modules()[0]
    return np.asarray(img)


def to_mask(array):
    """Boolean or 0/255 HxW array to a PIL L image of 0/255."""
    np = modules()[0]
    from PIL import Image
    return Image.fromarray(np.where(array, 255, 0).astype(np.uint8))  # 2-D uint8 is mode L


def square(px):
    """Square structuring element of side 2 * px + 1: the same neighborhood as Pillow MaxFilter/MinFilter."""
    np = modules()[0]
    return np.ones((2 * px + 1, 2 * px + 1), np.uint8)

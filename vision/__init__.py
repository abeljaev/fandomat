"""Vision модуль: камера, инференс, классификация."""

from vision.camera_manager import CameraManager
from vision.inference_engine import InferenceEngine

__all__ = ["CameraManager", "InferenceEngine", "InferenceClient"]


def __getattr__(name):
    if name == "InferenceClient":
        from vision.inference_service import InferenceClient
        return InferenceClient
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

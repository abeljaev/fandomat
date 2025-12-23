#!/usr/bin/env python3
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Suppress OpenCV warnings before importing cv2
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")

import cv2
import numpy as np
from ultralytics import YOLO


DEFAULT_MODEL_PATH = Path("/home/radxa/Documents/CODE/BottleClassifier/best_rknn_model")
DEFAULT_SOURCE_PATH = Path("/home/radxa/Documents/CODE/BottleClassifier/val/CAN")
DEFAULT_IMAGE_SIZE = 1024
DEFAULT_SAVE_BATCH = False
DEFAULT_REALTIME_DIR = Path("real_time")
DEFAULT_BURST = 3
DEFAULT_WARMUP_RUNS = 2
DEFAULT_MAX_CAMERAS = 5


def _get_top1(result):
    # Надёжно достаём top-1 для разных версий ultralytics
    probs = result.probs
    top1 = getattr(probs, "top1", int(probs.top5[0]))
    top1conf = getattr(probs, "top1conf", float(probs.top5conf[0]))
    return int(top1), float(top1conf)


def _total_ms(result):
    # result.speed: dict с ms по этапам; суммируем, иначе берём inference
    sp = getattr(result, "speed", None)
    if isinstance(sp, dict) and sp:
        return float(sum(sp.values()))
    if isinstance(sp, (int, float)):
        return float(sp)
    return float(getattr(getattr(result, "speed", {}), "get", lambda *_: 0)("inference", 0))


def _warmup_model(model: YOLO, imgsz: int, runs: int = 2) -> None:
    if runs <= 0:
        return
    print(f"Warming up model with {runs} random run(s)...")
    for idx in range(1, runs + 1):
        dummy = np.random.randint(0, 255, size=(imgsz, imgsz, 3), dtype=np.uint8)
        start = time.perf_counter()
        model.predict(source=dummy, imgsz=imgsz, verbose=False)
        took_ms = (time.perf_counter() - start) * 1000
        print(f"  Warmup #{idx}: {took_ms:.1f} ms")


def _get_camera_modes(camera_index: int) -> List[dict]:
    test_resolutions = [
        (320, 240),
        (640, 480),
        (800, 600),
        (1024, 768),
        (1280, 720),
        (1280, 1024),
        (1600, 1200),
        (1920, 1080),
        (2560, 1440),
        (2592, 1944),
        (3840, 2160),
    ]
    test_fps = [15, 24, 25, 30, 60]

    modes: List[dict] = []
    seen = set()
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        return modes

    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        for width, height in test_resolutions:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if (actual_width, actual_height) != (width, height):
                continue

            ret, _ = cap.read()
            if not ret:
                continue

            for fps in test_fps:
                cap.set(cv2.CAP_PROP_FPS, fps)
                fps_value = cap.get(cv2.CAP_PROP_FPS)

                # Fix FPS handling - ensure we always have a valid positive FPS
                if fps_value is None or fps_value <= 0:
                    actual_fps = fps
                else:
                    actual_fps = int(fps_value)

                # Only add modes with positive FPS
                if actual_fps <= 0:
                    continue

                key = (actual_width, actual_height, actual_fps)
                if key in seen:
                    continue
                seen.add(key)
                modes.append({
                    "width": actual_width,
                    "height": actual_height,
                    "fps": actual_fps,
                })
    finally:
        cap.release()

    modes.sort(key=lambda m: (m["width"] * m["height"], m["fps"]))
    return modes


def _probe_camera(camera_index: int) -> Optional[dict]:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        cap.release()
        return None

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    # Fix FPS handling - can't use 'or' with negative values
    fps_value = cap.get(cv2.CAP_PROP_FPS)
    if fps_value is None or fps_value <= 0:
        fps = 30.0
    else:
        fps = float(fps_value)
    cap.release()

    modes = _get_camera_modes(camera_index)
    if not modes:
        fallback_width = width if width > 0 else 640
        fallback_height = height if height > 0 else 480
        fallback_fps = int(fps) if fps > 0 else 30
        modes = [{
            "width": fallback_width,
            "height": fallback_height,
            "fps": fallback_fps,
        }]

    return {
        "index": camera_index,
        "default_width": width,
        "default_height": height,
        "default_fps": fps,
        "modes": modes,
    }


def _find_available_cameras(max_cameras: int = 5) -> List[dict]:
    cameras: List[dict] = []
    print(f"Scanning for available cameras (0-{max_cameras - 1})...")
    for idx in range(max_cameras):
        cam = _probe_camera(idx)
        if not cam:
            continue
        cameras.append(cam)
        width = cam["default_width"] or cam["modes"][0]["width"]
        height = cam["default_height"] or cam["modes"][0]["height"]
        fps = cam["default_fps"] if cam["default_fps"] else cam["modes"][0]["fps"]
        print(f"  Camera {idx}: {int(width)}x{int(height)} @ {fps:.1f} fps ({len(cam['modes'])} mode(s))")

    return cameras


def _select_camera(cameras: List[dict]) -> Optional[dict]:
    if not cameras:
        print("No cameras detected.")
        return None

    if len(cameras) == 1:
        cam = cameras[0]
        print(f"Only camera {cam['index']} detected, using it by default.")
        return cam

    print("\nДоступные камеры:")
    print("-" * 70)
    for idx, cam in enumerate(cameras, start=1):
        width = cam["default_width"] or cam["modes"][0]["width"]
        height = cam["default_height"] or cam["modes"][0]["height"]
        fps = cam["default_fps"] if cam["default_fps"] else cam["modes"][0]["fps"]
        print(f"[{idx}] Камера {cam['index']}: {int(width)}x{int(height)} @ {fps:.1f} fps ({len(cam['modes'])} режимов)")
    print("-" * 70)

    while True:
        try:
            choice = input(f"\nВыберите камеру (1-{len(cameras)}, Enter чтобы отменить): ").strip()
            if choice == "":
                return None
            idx = int(choice)
            if 1 <= idx <= len(cameras):
                return cameras[idx - 1]
            print("Некорректный номер, повторите ввод.")
        except ValueError:
            print("Введите число.")
        except KeyboardInterrupt:
            print("\nОтменено.")
            return None


def _select_camera_mode(camera: dict) -> Optional[dict]:
    modes = camera.get("modes", [])
    if not modes:
        fallback = {
            "width": int(camera.get("default_width") or 640),
            "height": int(camera.get("default_height") or 480),
            "fps": int(camera.get("default_fps") or 30),
        }
        print("Не удалось определить режимы камеры, используем по умолчанию.")
        return fallback

    if len(modes) == 1:
        mode = modes[0]
        print(f"Only one mode available: {mode['width']}x{mode['height']} @ {mode['fps']} fps")
        return mode

    print(f"\nДоступные режимы камеры {camera['index']}:")
    print("-" * 70)
    for idx, mode in enumerate(modes, start=1):
        res = f"{mode['width']}x{mode['height']}"
        print(f"  [{idx}] {res:15s} @ {mode['fps']:>4} fps")
    print("-" * 70)

    default_mode = modes[0]
    for mode in modes:
        if (mode["width"] == camera.get("default_width") and
                mode["height"] == camera.get("default_height")):
            default_mode = mode
            break

    while True:
        try:
            choice = input(f"\nВыберите режим (1-{len(modes)}, Enter по умолчанию): ").strip()
            if choice == "":
                print(f"Используем по умолчанию: {default_mode['width']}x{default_mode['height']} @ {default_mode['fps']} fps")
                return default_mode
            idx = int(choice)
            if 1 <= idx <= len(modes):
                selected = modes[idx - 1]
                print(f"Выбрано: {selected['width']}x{selected['height']} @ {selected['fps']} fps")
                return selected
            print(f"Некорректный номер. Введите 1-{len(modes)}.")
        except ValueError:
            print("Введите число или Enter.")
        except KeyboardInterrupt:
            print("\nОтменено.")
            return None


def _sanitize_class_name(name: str) -> str:
    sanitized = [ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name]
    clean = "".join(sanitized).strip("_")
    return clean or "class"


def _run_batch_inference(model: YOLO, source: str, imgsz: int, save: bool) -> None:
    results = model(source=source, imgsz=imgsz, save=save, verbose=False)
    for result in results:
        fname = Path(result.path).name
        names = result.names
        cidx, conf = _get_top1(result)
        cname = names[int(cidx)]
        t_ms = _total_ms(result)
        print(f"{fname} - {cname} - {conf:.4f} - {t_ms:.1f} ms")
    if save and len(results):
        outdir = Path(results[0].save_dir)
        print(f"saved: {outdir}")


def _run_camera_inference(model: YOLO, imgsz: int, output_dir: Path,
                          camera_index: int, camera_mode: dict, headless: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Failed to open camera {camera_index}")
        return

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_mode["width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_mode["height"])
    cap.set(cv2.CAP_PROP_FPS, camera_mode.get("fps", 30))

    requested_desc = f"{camera_mode['width']}x{camera_mode['height']} @ {camera_mode.get('fps', 30)} fps"
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Fix FPS handling - can't use 'or' with negative values
    fps_value = cap.get(cv2.CAP_PROP_FPS)
    if fps_value is None or fps_value <= 0:
        actual_fps = float(camera_mode.get("fps", 30))
    else:
        actual_fps = float(fps_value)

    # Test frame read before starting main loop
    print("\nTesting camera...")
    for attempt in range(3):
        ret, test_frame = cap.read()
        if ret and test_frame is not None and test_frame.size > 0:
            print(f"Camera test successful on attempt {attempt + 1}")
            break
        print(f"Attempt {attempt + 1}/3 failed, retrying...")
        time.sleep(0.5)
    else:
        print("Failed to read test frame after 3 attempts. Camera may not be ready.")
        cap.release()
        return

    window_name = f"Real-time classification (Camera {camera_index})"
    print("\nCamera ready!")
    print(f"Requested mode: {requested_desc}")
    print(f"Actual mode: {actual_width}x{actual_height} @ {actual_fps:.1f} fps")

    if headless:
        print("\nRunning in HEADLESS mode (no GUI window)")
        print("Type 'c' + Enter to capture, 'q' + Enter to quit.\n")
    else:
        print(f"Press SPACE for inference (captures {DEFAULT_BURST} frame(s)), 'q' to quit.\n")

    try:
        consecutive_failures = 0
        max_consecutive_failures = 5

        if headless:
            # Headless mode: use stdin for commands
            import select
            print("Waiting for commands (c=capture, q=quit)...")

        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                print(f"Warning: Failed to read frame ({consecutive_failures}/{max_consecutive_failures})")
                if consecutive_failures >= max_consecutive_failures:
                    print("Too many consecutive failures; exiting.")
                    break
                time.sleep(0.1)
                continue

            consecutive_failures = 0  # Reset on successful read

            if headless:
                # Headless mode: check stdin for commands
                time.sleep(0.01)  # Small delay to prevent CPU spinning

                # Check if input is available (non-blocking)
                if sys.platform != "win32":
                    # Unix-like systems
                    ready, _, _ = select.select([sys.stdin], [], [], 0)
                    if ready:
                        command = sys.stdin.readline().strip().lower()
                        if command == 'q':
                            break
                        elif command == 'c':
                            # Clear any remaining input in stdin buffer
                            while True:
                                ready_again, _, _ = select.select([sys.stdin], [], [], 0)
                                if not ready_again:
                                    break
                                sys.stdin.readline()
                            pass  # Will trigger capture below
                        else:
                            continue
                    else:
                        continue
                else:
                    # Windows: blocking read (simplified)
                    continue

            else:
                # GUI mode: display and wait for key
                display = frame.copy()
                cv2.putText(display, "SPACE: capture | Q: quit", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
                cv2.imshow(window_name, display)

                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:
                    break
                if key != 32:  # space
                    continue

            total_start = time.perf_counter()
            frames = [frame.copy()]
            for _ in range(1, DEFAULT_BURST):
                ret, new_frame = cap.read()
                if not ret:
                    print("Failed to capture all frames in burst; skipping.")
                    frames = []
                    break
                frames.append(new_frame.copy())
            if not frames:
                continue

            print(f"\nCaptured {len(frames)} frame(s) from camera {camera_index}. Running inference...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            total_infer_time = 0.0
            for idx, frame_img in enumerate(frames, start=1):
                infer_start = time.perf_counter()
                # Process each frame individually to avoid RKNN batch issues
                result = model.predict(source=frame_img, imgsz=imgsz, verbose=False)[0]
                infer_elapsed_ms = (time.perf_counter() - infer_start) * 1000
                total_infer_time += infer_elapsed_ms

                cidx, conf = _get_top1(result)
                cname = result.names[int(cidx)]
                safe_class = _sanitize_class_name(cname)
                
                filename = output_dir / f"{timestamp}_shot{idx}_{safe_class}.jpg"
                cv2.imwrite(str(filename), frame_img)
                print(f"  Shot {idx}: {cname} ({conf:.3f}) | inference {infer_elapsed_ms:.1f} ms | saved {filename.name}")

            

            total_elapsed_ms = (time.perf_counter() - total_start) * 1000
            print(f"Total pipeline: {total_elapsed_ms:.1f} ms (total inference: {total_infer_time:.1f} ms)")
            if headless:
                print("Ready for next command (c=capture, q=quit)...\n")
            else:
                print()


            #ВОТ ЗДЕСЬ


    
            

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        cap.release()
        if not headless:
            cv2.destroyAllWindows()


def _has_display() -> bool:
    """Check if display is available for GUI."""
    if sys.platform == "win32":
        return True
    display = os.environ.get("DISPLAY")
    return display is not None and display != ""


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", action="store_true", help="Run in real-time camera mode")
    ap.add_argument("--headless", action="store_true", help="Run without GUI window (auto-enabled if no display)")
    return ap.parse_args()


def main():
    args = parse_args()

    # Auto-enable headless mode if no display available
    headless = args.headless or not _has_display()
    if headless and not args.headless:
        print("No display detected, automatically enabling headless mode.")

    try:
        model = YOLO(str(DEFAULT_MODEL_PATH), task='classify')
    except Exception as exc:
        print(f"Failed to load model: {exc}")
        sys.exit(1)

    _warmup_model(model, imgsz=DEFAULT_IMAGE_SIZE, runs=DEFAULT_WARMUP_RUNS)

    if args.camera:
        cameras = _find_available_cameras(DEFAULT_MAX_CAMERAS)
        camera = _select_camera(cameras)
        if camera is None:
            print("No camera selected. Exiting.")
            return

        mode = _select_camera_mode(camera)
        if mode is None:
            print("No camera mode selected. Exiting.")
            return

        _run_camera_inference(
            model=model,
            imgsz=DEFAULT_IMAGE_SIZE,
            output_dir=DEFAULT_REALTIME_DIR,
            camera_index=camera["index"],
            camera_mode=mode,
            headless=headless,
        )
    else:
        _run_batch_inference(model, str(DEFAULT_SOURCE_PATH), DEFAULT_IMAGE_SIZE, DEFAULT_SAVE_BATCH)


if __name__ == "__main__":
    main()

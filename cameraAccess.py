"""
JARVIS Camera Access Module (UPGRADED 2026-08)
================================================================
Switched from LLaVA `/api/generate` + base64 → Qwen 2.5 VL `/api/chat` + image blocks.

Changes:
    - New model: redule26/huihui_ai_qwen2.5-vl-7b-abliterated (uncensored)
    - New API: /api/chat with image content blocks (instead of /api/generate)
    - Detail mode: llama3.2-vision:11b for high-detail queries
    - Better OCR and screen reading
    - No preaching on sensitive content
"""
import cv2
import requests
import base64
import os
import time
import sys

# Add parent dir for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import config
except ImportError:
    class config:
        VISION_MODEL_FAST = "redule26/huihui_ai_qwen2.5-vl-7b-abliterated"
        VISION_MODEL_DETAIL = "llama3.2-vision:11b"
        OLLAMA_BASE_URL = "http://localhost:11434"
        OLLAMA_TIMEOUT = None

OLLAMA_CHAT_URL = f"{config.OLLAMA_BASE_URL}/api/chat"


def find_working_camera():
    """Try camera indices 0-4 and return the first one that works."""
    for index in range(5):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)  # CAP_DSHOW is faster on Windows
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                return index
        cap.release()
    return None


def capture_image(camera_index=None, filename="capture.jpg"):
    """Capture a single frame from the camera."""
    if camera_index is None:
        camera_index = find_working_camera()
        if camera_index is None:
            print("[Vision]: No working camera found.")
            return None

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)

    if not cap.isOpened():
        print(f"[Vision]: Could not open camera at index {camera_index}.")
        return None

    # Let camera warm up — some cameras output dark/blurry first frames
    for _ in range(5):
        cap.read()
        time.sleep(0.05)

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        print("[Vision]: Failed to capture frame.")
        return None

    # Resize for faster processing while keeping good detail
    frame = cv2.resize(frame, (1280, 720))

    cv2.imwrite(filename, frame, [cv2.IMWRITE_JPEG_QUALITY, 97])
    return filename


def encode_image(image_path):
    """Encode image to base64 string for API."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def ask_vision(image_path, prompt="Describe what you see in this image in detail.", detail_mode=False):
    """
    Send image to vision model and return the response.

    Tries the NEW /api/chat endpoint with image content blocks first (Qwen 2.5 VL format).
    If that fails (HTTP 400), falls back to the OLD /api/generate endpoint with base64
    images array (LLaVA format) — some abliterated model variants only support this.

    Set detail_mode=True to use the higher-quality 11B vision model.
    """
    if not os.path.exists(image_path):
        return "Vision error: image file not found."

    img_b64 = encode_image(image_path)

    # Pick model based on detail mode
    model = config.VISION_MODEL_DETAIL if detail_mode else config.VISION_MODEL_FAST

    # ── Try /api/chat format first (Qwen 2.5 VL native) ──────────────
    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": f"data:image/jpeg;base64,{img_b64}"
                            }
                        ]
                    }
                ],
                "stream": False,
                "options": {
                    "num_predict": 300,
                    "temperature": 0.3
                }
            },
            timeout=config.OLLAMA_TIMEOUT
        )

        if response.status_code == 200:
            result = response.json().get("message", {}).get("content", "").strip()
            if result:
                return result
        # If status != 200, fall through to the legacy API below
    except requests.exceptions.ConnectionError:
        return "Vision error: could not connect to Ollama. Make sure it is running."
    except Exception as e:
        print(f"[Vision]: /api/chat failed ({e}), trying legacy /api/generate format...")

    # ── Fallback: /api/generate format (LLaVA-style, works with more models) ──
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {
                    "num_predict": 300,
                    "temperature": 0.3
                }
            },
            timeout=config.OLLAMA_TIMEOUT
        )

        if response.status_code == 200:
            result = response.json().get("response", "").strip()
            if result:
                return result
            return "Vision returned an empty response."
        else:
            return f"Vision error: server returned status {response.status_code}. Both /api/chat and /api/generate failed."
    except requests.exceptions.ConnectionError:
        return "Vision error: could not connect to Ollama. Make sure it is running."
    except Exception as e:
        return f"Vision error: {e}"


def see(prompt=None, detail_mode=False):
    """
    Main function called by Jarvis.
    Captures an image, sends it to vision model, returns the description.
    Also stores the description in vision memory for later recall.

    Set detail_mode=True for high-detail analysis (uses 11B model, slower).
    """
    # If no prompt provided, use the JARVIS personality prompt
    if prompt is None or prompt == "Describe what you see in detail.":
        prompt = """You are JARVIS, a witty and observant AI assistant. Look at this image and describe what you see in a natural, conversational way — like a friend who just walked into the room and is commenting on what they notice.

Be observant, engaging, and add a touch of personality. Notice interesting details, describe the mood or atmosphere, and comment on things that stand out. Use natural conversational language, not a clinical list.

Address the user as "Sir". Keep it under 4-5 sentences unless there's a lot to describe."""
    print(f"[Vision]: Capturing image... (detail_mode={detail_mode})")
    img_path = capture_image()

    if not img_path:
        return "I was unable to access the camera."

    print(f"[Vision]: Analyzing image with {config.VISION_MODEL_DETAIL if detail_mode else config.VISION_MODEL_FAST}...")
    result = ask_vision(img_path, prompt, detail_mode=detail_mode)

    # Store in vision memory for later recall ("what did you see earlier?")
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from modules.vision_memory import get_vision_memory
        vm = get_vision_memory()
        vm.store(img_path, result, source="camera")
    except Exception as e:
        print(f"[Vision]: Memory store error: {e}")

    try:
        os.remove(img_path)
    except Exception:
        pass

    return result


def pull_vision_model_if_needed():
    """Check if vision model is available, pull if not."""
    try:
        r = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]

        # Check for either vision model
        has_fast = any(config.VISION_MODEL_FAST in m for m in models)
        has_detail = any(config.VISION_MODEL_DETAIL in m for m in models)

        if has_fast:
            print(f"[Vision]: Fast model '{config.VISION_MODEL_FAST}' is available.")
        else:
            print(f"[Vision]: Pulling '{config.VISION_MODEL_FAST}' (this may take a while)...")
            import subprocess
            subprocess.run(["ollama", "pull", config.VISION_MODEL_FAST])
            print(f"[Vision]: '{config.VISION_MODEL_FAST}' is ready.")

        if not has_detail:
            print(f"[Vision]: Detail model '{config.VISION_MODEL_DETAIL}' not yet pulled.")
            print(f"[Vision]: Run 'ollama pull {config.VISION_MODEL_DETAIL}' to enable high-detail mode.")
    except Exception as e:
        print(f"[Vision]: Could not check model availability: {e}")


# Test mode
if __name__ == "__main__":
    print("Testing camera vision module (NEW Qwen 2.5 VL API)...\n")
    pull_vision_model_if_needed()
    print("\n--- Fast mode test ---")
    output = see("Describe everything you can see in detail.")
    print("\nResult:\n")
    print(output)

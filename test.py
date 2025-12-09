import requests
import pygame
import tempfile
import os

HF_API_KEY = "YOUR_HUGGINGFACE_API_KEY"

def speak(text):
    print(f"AI: {text}")
    if not text.strip():
        return

    url = "https://api-inference.huggingface.co/models/coqui/xtts-v2"

    headers = {
        "Authorization": f"Bearer {HF_API_KEY}"
    }

    payload = {
        "inputs": text,
        "parameters": {
            "language": "hi",       # Hindi + English mixed (Hinglish)
            "speaker": "male"       # Deep male voice
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print(response.text)
        return

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fp:
        fp.write(response.content)
        temp_path = fp.name

    pygame.mixer.init()
    pygame.mixer.music.load(temp_path)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)

    pygame.mixer.quit()
    os.remove(temp_path)

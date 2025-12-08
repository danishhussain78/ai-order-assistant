import json
import pandas as pd
import requests
import speech_recognition as sr
from gtts import gTTS
import pygame
import sys
import re
import time
import tempfile
import os
from datetime import datetime

import pyttsx3

engine = pyttsx3.init()
voices = engine.getProperty('voices')

# Select male voice (on Windows, usually index 0 or 1)
for v in voices:
    print(v.id, v.name)
engine.setProperty('voice', voices[0].id)  # choose male voice index

def speak(text):
    text = clean_tts_text(text)
    print(f"AI: {text}")
    engine.say(text)
    engine.runAndWait()


# -----------------------------
# CONFIG
# -----------------------------
OLLAMA_HOST = "http://localhost:11500"
MODEL = "llama3.2:3b"
MENU_FILE = "menu.xlsx"
USE_TTS = True
ORDERS_FILE = "orders.json"  # File to save confirmed orders

# -----------------------------
# TEXT CLEANING
# -----------------------------
def clean_tts_text(text):
    """Clean text for TTS - remove problematic characters"""
    if not text:
        return ""
    
    # Remove emojis and non-ASCII characters
    text = text.encode("ascii", "ignore").decode()
    
    # Remove markdown formatting
    text = re.sub(r'[*_`~#]', '', text)
    
    # Remove weird unicode spaces & control chars
    text = re.sub(r"[\u2028\u2029\u200b-\u200f]", "", text)
    
    # Remove newlines and tabs
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    
    # Remove quotes that might cause issues
    text = text.replace('"', '').replace("'", '')
    
    return text.strip()

# -----------------------------
# SETUP TTS (using gTTS)
# -----------------------------
def init_audio():
    """Initialize pygame mixer for audio playback"""
    if not USE_TTS:
        return False
    try:
        pygame.mixer.init()
        print("✅ Audio system initialized (gTTS + pygame)")
        return True
    except Exception as e:
        print(f"⚠️ Audio initialization failed: {e}")
        return False

audio_ready = init_audio()

# def speak(text):
#     """Speak text using gTTS (Google Text-to-Speech)"""
#     text = clean_tts_text(text) if text else ""
    
#     print(f"AI: {text}")
    
#     if not USE_TTS or not audio_ready:
#         return
    
#     if not text or len(text.strip()) == 0:
#         return
    
#     temp_file = None
#     try:
#         # Create a temporary file
#         with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
#             temp_file = fp.name
        
#         print(f"🔊 Generating speech...")
#         # Generate speech with gTTS (tld='com.au' gives more natural male-like voice)
#         #make fast speak
#         tts = gTTS(text=text, lang='hi', slow=False, tld='co.in')  # UK accent sounds more natural
#         tts.save(temp_file)
        
#         print(f"🔊 Playing audio...")
#         # Load and play
#         pygame.mixer.music.load(temp_file)
#         pygame.mixer.music.play()
        
#         # Wait for playback to finish
#         while pygame.mixer.music.get_busy():
#             pygame.time.Clock().tick(10)
        
#         print("✅ Audio finished")
        
#     except Exception as e:
#         print(f"❌ TTS Error: {e}")
#     finally:
#         # Cleanup
#         try:
#             pygame.mixer.music.stop()
#             pygame.mixer.music.unload()
#         except:
#             pass
        
#         if temp_file and os.path.exists(temp_file):
#             try:
#                 time.sleep(0.1)  # Small delay before deleting
#                 os.unlink(temp_file)
#             except:
#                 pass

# -----------------------------
# LOAD MENU
# -----------------------------
def load_menu(file_path):
    df = pd.read_excel(file_path)
    menu_dict = {}
    menu_items_flat = []
    for _, row in df.iterrows():
        cat = row["Category"].strip()
        item = row["Item"].strip()
        menu_dict.setdefault(cat, []).append(item)
        menu_items_flat.append(item.lower())
    return menu_dict, menu_items_flat

MENU, MENU_ITEMS_FLAT = load_menu(MENU_FILE)

# -----------------------------
# SPEECH TO TEXT
# -----------------------------
def transcribe_microphone():
    r = sr.Recognizer()
    r.energy_threshold = 1300
    r.dynamic_energy_threshold = True
    r.pause_threshold = 1.0
    
    with sr.Microphone() as source:
        print("\n🎤 Listening...")
        r.adjust_for_ambient_noise(source, duration=0.3)
        
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=10)
            print("🔄 Processing speech...")
        except sr.WaitTimeoutError:
            print("❌ No speech detected")
            return None
    
    try:
        text = r.recognize_google(audio)
        print(f"✅ You said: {text}")
        return text
    except sr.UnknownValueError:
        print("❌ Could not understand audio")
        return None
    except Exception as e:
        print(f"❌ Speech recognition failed: {e}")
        return None

# -----------------------------
# LLM CALL
# -----------------------------
def call_llm(messages, system_prompt=None):
    msgs = messages.copy()
    if system_prompt:
        msgs.insert(0, {"role": "system", "content": system_prompt})
    
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json={
            "model": MODEL,
            "messages": msgs,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 100
            }
        }, timeout=30)
        
        data = r.json()
        response = data.get("message", {}).get("content", "") or data.get("completion", "")

        if response:
            return response.strip()
        else:
            return "I'm having trouble right now. Could you repeat that?"
            
    except requests.exceptions.Timeout:
        return "Sorry, I'm taking too long to think. Can you repeat that?"
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return "I'm having trouble processing that. Could you say it again?"

# -----------------------------
# ORDER PARSER
# -----------------------------
def extract_quantity(text):
    number_words = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10
    }
    
    match = re.search(r'\b(\d+)\b', text)
    if match:
        return int(match.group(1))
    
    for word, num in number_words.items():
        if word in text.lower():
            return num
    
    return 1

def parse_order(user_text, menu, menu_flat):
    items_found = []
    text_lower = user_text.lower()
    
    for cat, items in menu.items():
        for item in items:
            item_lower = item.lower()
            if item_lower in text_lower:
                idx = text_lower.find(item_lower)
                context = text_lower[max(0, idx-20):idx+len(item_lower)+5]
                qty = extract_quantity(context)
                
                items_found.append({
                    "category": cat,
                    "name": item,
                    "quantity": qty
                })
    
    return items_found

# -----------------------------
# ORDER SAVING
# -----------------------------
def save_order_to_file(order_data):
    """Save confirmed order to JSON file"""
    try:
        # Load existing orders
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, 'r') as f:
                orders = json.load(f)
        else:
            orders = []
        
        # Add new order
        orders.append(order_data)
        
        # Save back to file
        with open(ORDERS_FILE, 'w') as f:
            json.dump(orders, f, indent=2)
        
        print(f"✅ Order saved to {ORDERS_FILE}")
        return True
    except Exception as e:
        print(f"❌ Failed to save order: {e}")
        return False

# -----------------------------
# POS API MOCK
# -----------------------------
def send_to_pos(order):
    """Send order to POS system and save to file"""
    import random
    from datetime import datetime
    
    order_id = f"ORD{random.randint(1000,9999)}"
    
    # Create complete order data
    order_data = {
        "order_id": order_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": order["items"],
        "total_items": len(order["items"]),
        "status": "confirmed"
    }
    
    print("\n🧾 Sending order to POS...")
    print(json.dumps(order_data, indent=2))
    
    # Save to JSON file
    save_order_to_file(order_data)
    
    return {"status": "success", "order_id": order_id}

# -----------------------------
# ORDER SUMMARY
# -----------------------------
def generate_order_summary(order_items):
    if not order_items:
        return "No items ordered."
    
    summary_lines = []
    for item in order_items:
        summary_lines.append(f"{item['quantity']} {item['name']}")
    
    return ", ".join(summary_lines)

# -----------------------------
# CONVERSATION MEMORY
# -----------------------------
conversation_memory = []
current_order = []

# -----------------------------
# SYSTEM PROMPT
# -----------------------------
SYSTEM_PROMPT = f"""You are a friendly restaurant order-taking assistant. Follow these rules strictly:

1. ONLY mention items from this menu: {', '.join(MENU_ITEMS_FLAT)}
2. Be VERY concise - maximum 15 words in your response
3. Be natural and conversational like a real human server
4. If customer asks for items NOT on the menu, politely say "Sorry, we don't have that" and suggest similar items
5. Help customers with quantities or clarifications
6. Never make up menu items
7. Don't ask multiple questions at once

Available menu items: {', '.join(MENU_ITEMS_FLAT)}

Respond in ONE short sentence only."""

# -----------------------------
# AGENT LOOP
# -----------------------------
def main():
    global current_order, conversation_memory
    
    # Test TTS
    # print("\n🧪 Testing audio system...")
    # speak("Testing audio. If you hear this, TTS is working.")
    # time.sleep(0.5)  # Wait between tests
    
    # speak("Second test. Can you hear this too?")
    # time.sleep(0.5)
    
    speak("Hi! Welcome to our restaurant. What can I get you today?")

    while True:
        mode = "voice"  # Default to voice mode
        
        if mode == "finish":
            if current_order:
                summary = generate_order_summary(current_order)
                speak(f"Let me confirm: {summary}. Is this correct?")
                
                confirm = input("Confirm order? (yes/no): ").strip().lower()
                if confirm == "yes":
                    pos_resp = send_to_pos({"items": current_order})
                    speak(f"Perfect! Your order is placed. Order number {pos_resp['order_id']}. Thank you!")
                    current_order = []
                    conversation_memory = []
                else:
                    speak("No problem. What would you like to change?")
                    continue
            else:
                speak("You haven't ordered anything yet. What would you like?")
            continue

        # Get user input
        if mode == "voice":
            user_text = transcribe_microphone()
        else:
            user_text = input("You: ").strip()

        if not user_text:
            continue

        if user_text.lower() in ["exit", "quit", "bye", "cancel", "finish", "done", "that's all", "thats all"]:
            if user_text.lower() in ["finish", "done", "that's all", "thats all"] and current_order:
                # Show order summary
                print("\n" + "="*50)
                print("📋 ORDER SUMMARY")
                print("="*50)
                for i, item in enumerate(current_order, 1):
                    print(f"{i}. {item['quantity']}x {item['name']} ({item['category']})")
                print("="*50 + "\n")
                
                summary = generate_order_summary(current_order)
                speak(f"Let me confirm your order: {summary}.")
                
                # Voice confirmation
                speak("Please say yes to confirm, or no to cancel.")
                confirm_response = transcribe_microphone()
                
                if confirm_response and "yes" in confirm_response.lower():
                    pos_resp = send_to_pos({"items": current_order})
                    speak(f"Perfect! Your order is confirmed. Order number {pos_resp['order_id']}. Thank you!")
                    current_order = []
                    conversation_memory = []
                    break
                else:
                    speak("Order cancelled. What would you like to change?")
                    continue
            else:
                speak("Thanks for visiting! Have a great day!")
                break

        # Add to conversation memory
        conversation_memory.append({"role": "user", "content": user_text})

        # Parse for menu items
        found_items = parse_order(user_text, MENU, MENU_ITEMS_FLAT)

        if found_items:
            for item in found_items:
                existing = next((x for x in current_order if x['name'] == item['name']), None)
                if existing:
                    existing['quantity'] += item['quantity']
                else:
                    current_order.append(item)
            
            items_str = ", ".join([f"{it['quantity']} {it['name']}" for it in found_items])
            response = f"Got it! Added {items_str}. Anything else?"
            conversation_memory.append({"role": "assistant", "content": response})
            speak(response)
        else:
            print("📝 Asking AI...")
            response = call_llm(conversation_memory, SYSTEM_PROMPT)
            
            if response and len(response.strip()) > 0:
                conversation_memory.append({"role": "assistant", "content": response})
                speak(response)
            else:
                fallback = "Sorry, could you repeat that?"
                conversation_memory.append({"role": "assistant", "content": fallback})
                speak(fallback)
        
        # Keep conversation memory manageable
        if len(conversation_memory) > 20:
            conversation_memory = conversation_memory[-20:]

if __name__ == "__main__":
    main()
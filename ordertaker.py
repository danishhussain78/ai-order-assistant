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

# -----------------------------
# CONFIG
# -----------------------------
OLLAMA_HOST = "http://10.0.3.3:11434/api/chat"
MODEL = "llama3.1:8b"
MENU_FILE = "menu.xlsx"
USE_TTS = True
ORDERS_FILE = "orders.json"
ORDER_STATE_FILE = "current_order_state.json"

# Order state tracking
class OrderState:
    GREETING = "greeting"
    ASK_ITEM = "ask_item"
    ASK_FLAVOR = "ask_flavor"
    ASK_SIZE = "ask_size"
    ASK_MORE = "ask_more"
    COLLECT_ADDRESS = "collect_address"
    COLLECT_PHONE = "collect_phone"
    CONFIRM_ORDER = "confirm_order"
    COMPLETED = "completed"

# -----------------------------
# TEXT CLEANING
# -----------------------------
def clean_tts_text(text):
    """Clean text for TTS - remove problematic characters"""
    if not text:
        return ""
    
    text = text.encode("ascii", "ignore").decode()
    text = re.sub(r'[*_`~#]', '', text)
    text = re.sub(r"[\u2028\u2029\u200b-\u200f]", "", text)
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    text = re.sub(r"\s+", " ", text)
    text = text.replace('"', '').replace("'", '')
    
    return text.strip()

# -----------------------------
# SETUP TTS
# -----------------------------
def init_audio():
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

def speak(text):
    text = clean_tts_text(text) if text else ""
    print(f"AI: {text}")
    
    if not USE_TTS or not audio_ready or not text or len(text.strip()) == 0:
        return
    
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            temp_file = fp.name
        
        # print(f"🔊 Generating speech...")
        tts = gTTS(text=text, lang='en', slow=False, tld='co.uk')
        tts.save(temp_file)
        
        # print(f"🔊 Playing audio...")
        pygame.mixer.music.load(temp_file)
        pygame.mixer.music.play()
        
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
        
        # print("✅ Audio finished")
        
    except Exception as e:
        print(f"❌ TTS Error: {e}")
    finally:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except:
            pass
        
        if temp_file and os.path.exists(temp_file):
            try:
                time.sleep(0.1)
                os.unlink(temp_file)
            except:
                pass

# -----------------------------
# LOAD MENU
# -----------------------------
def load_menu(file_path):
    df = pd.read_excel(file_path)
    menu_dict = {}
    menu_items_flat = []
    
    pizza_flavors = []
    pizza_sizes = ["small", "regular", "medium", "large", "xxl"]
    
    for _, row in df.iterrows():
        cat = row["Category"].strip()
        item = row["Item"].strip()
        menu_dict.setdefault(cat, []).append(item)
        menu_items_flat.append(item.lower())
        
        if "pizza" in cat.lower() or "flavor" in cat.lower():
            pizza_flavors.append(item.lower())
    
    return menu_dict, menu_items_flat, pizza_flavors, pizza_sizes

MENU, MENU_ITEMS_FLAT, PIZZA_FLAVORS, PIZZA_SIZES = load_menu(MENU_FILE)

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
            # print("🔄 Processing speech...")
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

def get_user_input(voice_mode=True):
    if voice_mode:
        user_text = transcribe_microphone()
        if user_text:
            return user_text
        print("⌨️ Voice recognition failed. Please type your response:")
        return input("You: ").strip()
    else:
        return input("You: ").strip()

# -----------------------------
# ORDER PARSING HELPERS
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

def detect_pizza_flavor(text):
    text_lower = text.lower()
    for flavor in PIZZA_FLAVORS:
        if flavor in text_lower:
            return flavor
    return None

def detect_pizza_size(text):
    text_lower = text.lower()
    for size in PIZZA_SIZES:
        if size in text_lower:
            return size
    return None

def is_pizza_request(text):
    text_lower = text.lower()
    pizza_keywords = ["pizza", "pie"]
    return any(keyword in text_lower for keyword in pizza_keywords)

# -----------------------------
# ORDER SAVING
# -----------------------------
def save_order_to_file(order_data):
    try:
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, 'r') as f:
                orders = json.load(f)
        else:
            orders = []
        
        orders.append(order_data)
        
        with open(ORDERS_FILE, 'w') as f:
            json.dump(orders, f, indent=2)
        
        print(f"✅ Order saved to {ORDERS_FILE}")
        return True
    except Exception as e:
        print(f"❌ Failed to save order: {e}")
        return False

def save_order_to_csv(order_data):
    try:
        csv_file = "orders.csv"
        
        csv_data = {
            'Order ID': order_data['order_id'],
            'Timestamp': order_data['timestamp'],
            'Items': '; '.join([f"{item['quantity']}x {item['size']} {item['name']}" for item in order_data['items']]),
            'Address': order_data.get('address', ''),
            'Phone': order_data.get('phone', ''),
            'Total Items': order_data['total_items'],
            'Status': order_data['status']
        }
        
        file_exists = os.path.exists(csv_file)
        df = pd.DataFrame([csv_data])
        
        if file_exists:
            df.to_csv(csv_file, mode='a', header=False, index=False)
        else:
            df.to_csv(csv_file, mode='w', header=True, index=False)
        
        print(f"✅ Order saved to {csv_file}")
        return True
    except Exception as e:
        print(f"❌ Failed to save order to CSV: {e}")
        return False

# -----------------------------
# POS API
# -----------------------------
def send_to_pos(order):
    import random
    
    order_id = f"ORD{random.randint(1000,9999)}"
    
    order_data = {
        "order_id": order_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": order["items"],
        "address": order.get("address", ""),
        "phone": order.get("phone", ""),
        "total_items": len(order["items"]),
        "status": "confirmed"
    }
    
    print("\n🧾 Sending order to POS...")
    print(json.dumps(order_data, indent=2))
    
    save_order_to_file(order_data)
    save_order_to_csv(order_data)
    
    return {"status": "success", "order_id": order_id}

# -----------------------------
# LLM CALL
# -----------------------------

# -----------------------------
# LLM CALL
# -----------------------------
def call_llm(messages):
    """Call LLM with conversation history"""
    try:
        # Use existing OLLAMA_HOST which already has /api/chat if user modified it, 
        # but to be safe and consistent with user request:
        url = OLLAMA_HOST 
        
        if "/api/chat" not in OLLAMA_HOST:
             url = f"{OLLAMA_HOST}/api/chat"

        # print(f"📡 Connecting to LLM at {url}...")
        
        payload = {
            "model": MODEL,
            "messages": messages,
            "options": {
                "temperature": 0.3,
                "num_predict": 100
            }
        }
        
        response = requests.post(url, json=payload, stream=True, timeout=15)
        full_response_text = ""
        
        # print("🤖 AI generating: ", end="", flush=True)
        
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode("utf-8"))
                    if "message" in data:
                        content = data["message"]["content"]
                        # print(content, end="", flush=True)
                        full_response_text += content
                except:
                    pass
        # print() # Newline after streaming
        
        clean_text = full_response_text.strip()
        
        if clean_text:
            # We return the RAW response now, so the tools are preserved for the parser.
            # The cleaning will happen in query_llm or separate helper.
            return clean_text, True 
        else:
            return "Sorry, could you repeat that?", False
            
    except Exception as e:
        print(f"\n❌ LLM Error: {e}")
        return "I didn't catch that. Could you say it again?", False


# -----------------------------
# MAIN ORDER SYSTEM
# -----------------------------
class OrderSystem:
    def __init__(self):
        self.state = OrderState.GREETING
        self.current_order = []
        self.temp_item = {}
        self.customer_address = ""
        self.customer_phone = ""
        
        # Initialize conversation history
        pizza_flavors_str = ", ".join([f.title() for f in PIZZA_FLAVORS])
        self.system_prompt = f"""You are a friendly restaurant order assistant.

AVAILABLE PIZZA FLAVORS: {pizza_flavors_str}
AVAILABLE SIZES: Small, Regular, Medium, Large, XXL

TOOLS:
1. `[ADD_ITEM: {{"name": "...", "size": "...", "quantity": ...}}]` 
   - Use this IMMEDIATELY when the user confirms an item.
2. `[SET_DETAILS: {{"address": "...", "phone": "..."}}]`
   - Use this when the user provides address and phone.
3. `[SAVE_ORDER]`
   - Use this ONLY when the order is CONFIRMED and you have address and phone.

RULES:
1. Keep responses SHORT (max 15 words).
2. Use tools explicitly with valid JSON.
3. If address/phone is missing, ask for it.
4. Do NOT use `[SAVE_ORDER]` if you don't have the address and phone.
5. Example: "Got it! [SET_DETAILS: {{"address": "123 Main", "phone": "555"}}] Confirm order?"

Respond naturally."""

        self.conversation_history = [
            {"role": "system", "content": self.system_prompt}
        ]

    def add_user_message(self, text, context=""):
        # Append user message with optional context injection
        content = text
        if context:
            content = f"Instruction: {context}\nUser: {text}"
        
        self.conversation_history.append({"role": "user", "content": content})

    def add_assistant_message(self, text):
        self.conversation_history.append({"role": "assistant", "content": text})
        
    def query_llm(self, user_text, context=""):
        self.add_user_message(user_text, context)
        # Call LLM - getting RAW response now
        response, _ = call_llm(self.conversation_history) 
        
        # Parse tools from raw response
        self.parse_and_execute_tools(response)
        
        # Clean response for TTS and history (so tools don't pollute the context/speech)
        cleaned_response = re.sub(r'\[.*?\]', '', response).strip()
        if not cleaned_response: cleaned_response = "Done." # Fallback if only tool was output
        
        self.add_assistant_message(response) # Add raw response to history so LLM knows it called the tool
        return cleaned_response, False 
    
    def parse_and_execute_tools(self, response):
        """Parse and execute tools from LLM response"""
        # Parse ADD_ITEM
        add_item_match = re.search(r'\[ADD_ITEM: ({.*?})\]', response)
        if add_item_match:
            try:
                item_data = json.loads(add_item_match.group(1))
                self.current_order.append(item_data)
                print(f"📦 Added item: {item_data}")
            except Exception as e:
                print(f"❌ Failed to parse item: {e}")
        
        # Parse SET_DETAILS
        details_match = re.search(r'\[SET_DETAILS: ({.*?})\]', response)
        if details_match:
            try:
                details = json.loads(details_match.group(1))
                if "address" in details: self.customer_address = details["address"]
                if "phone" in details: self.customer_phone = details["phone"]
                print(f"📝 Details set: {details}")
            except:
                print("❌ Failed to parse details")
                
        # Parse SAVE_ORDER
        if "[SAVE_ORDER]" in response:
            if self.current_order and self.customer_address and self.customer_phone:
                pos_resp = send_to_pos({
                    "items": self.current_order,
                    "address": self.customer_address,
                    "phone": self.customer_phone
                })
                speak(f"Order {pos_resp['order_id']} placed successfully!")
                time.sleep(1)
                sys.exit(0) # Exit after saving
            else:
                print("❌ Missing details, cannot save yet.")
        
    def process_input(self, user_text):
        text_lower = user_text.lower()
        
        # Handle exit commands
        if text_lower in ["exit", "quit", "bye", "cancel"]:
            speak("Thanks for calling! Have a great day!")
            return "EXIT"
        
        # State machine
        if self.state == OrderState.GREETING:
            return self.handle_greeting(user_text)
            
        elif self.state == OrderState.ASK_ITEM:
            return self.handle_ask_item(user_text)
            
        elif self.state == OrderState.ASK_FLAVOR:
            return self.handle_ask_flavor(user_text)
            
        elif self.state == OrderState.ASK_SIZE:
            return self.handle_ask_size(user_text)
            
        elif self.state == OrderState.ASK_MORE:
            return self.handle_ask_more(user_text)
            
        elif self.state == OrderState.COLLECT_ADDRESS:
            return self.handle_collect_address(user_text)
            
        elif self.state == OrderState.COLLECT_PHONE:
            return self.handle_collect_phone(user_text)
            
        elif self.state == OrderState.CONFIRM_ORDER:
            return self.handle_confirm_order(user_text)
    
    def handle_greeting(self, user_text):
        text_lower = user_text.lower()
        
        # Check if asking for menu first
        menu_keywords = ["what", "which", "list", "menu", "have", "available", "options", "flavors", "flavours", "all", "tell me"]
        if any(keyword in text_lower for keyword in menu_keywords) and not is_pizza_request(text_lower):
            flavor_list = [flavor.title() for flavor in PIZZA_FLAVORS]
            
            # If they want ALL flavors
            if "all" in text_lower or "tell me all" in text_lower:
                flavors_str = ", ".join(flavor_list)
                speak(f"We have {flavors_str}. What would you like to order?")
            else:
                flavors_str = ", ".join(flavor_list[:8])
                speak(f"We have pizzas like {flavors_str}, and more. What would you like?")
            self.state = OrderState.ASK_ITEM
            return "CONTINUE"
        
        if is_pizza_request(user_text):
            qty = extract_quantity(user_text)
            self.temp_item = {"quantity": qty, "category": "Pizza"}
            
            # Check if flavor is already mentioned
            flavor = detect_pizza_flavor(user_text)
            if flavor:
                self.temp_item["name"] = flavor.title()
                self.state = OrderState.ASK_SIZE
                speak(f"Great! {qty} {flavor.title()} pizza. Which size? Small, Regular, Medium, Large, or XXL?")
            else:
                self.state = OrderState.ASK_FLAVOR
                speak(f"Sure! {qty} pizza. Which flavor? Chicken Surprise, Jamaican BBQ, Chicago Bold Fold, or any other?")
        else:
            # Use LLM for greeting responses
            # print("🤖 Using AI to respond...")
            context = "Customer just started conversation. Guide them to order pizza."
            response, save_trigger = self.query_llm(user_text, context)
            speak(response)
            if save_trigger:
                 # If LLM triggered save here (unlikely in greeting but possible if user says "reorder last" etc)
                 # For now just log it or ignore if no items.
                 pass
        return "CONTINUE"
    
    def handle_ask_item(self, user_text):
        text_lower = user_text.lower()
        
        # Check for menu inquiry
        menu_keywords = ["what", "which", "list", "menu", "have", "available", "all", "tell me"]
        if any(keyword in text_lower for keyword in menu_keywords):
            flavor_list = [flavor.title() for flavor in PIZZA_FLAVORS]
            
            if "all" in text_lower or "tell me all" in text_lower:
                flavors_str = ", ".join(flavor_list)
                speak(f"We have {flavors_str}. What would you like?")
            else:
                flavors_str = ", ".join(flavor_list[:8])
                speak(f"We have {flavors_str}, and more. What would you like?")
            return "CONTINUE"
        
        if is_pizza_request(user_text):
            qty = extract_quantity(user_text)
            self.temp_item = {"quantity": qty, "category": "Pizza"}
            
            flavor = detect_pizza_flavor(user_text)
            if flavor:
                self.temp_item["name"] = flavor.title()
                self.state = OrderState.ASK_SIZE
                speak(f"{qty} {flavor.title()} pizza. Which size?")
            else:
                self.state = OrderState.ASK_FLAVOR
                speak(f"{qty} pizza. Which flavor would you like?")
        else:
            # Use LLM for intelligent response
            # print("🤖 Using AI to understand...")
            context = "Customer should order pizza. Guide them naturally."
            response, save_trigger = self.query_llm(user_text, context)
            speak(response)
            if save_trigger:
                 pass # Cannot save without items
        return "CONTINUE"
    
    def handle_ask_flavor(self, user_text):
        text_lower = user_text.lower()
        
        # Check if asking for menu/flavors list
        menu_keywords = ["what", "which", "list", "menu", "flavors", "flavours", "options", "have", "available", "all", "tell me"]
        if any(keyword in text_lower for keyword in menu_keywords):
            # List all pizza flavors
            flavor_list = [flavor.title() for flavor in PIZZA_FLAVORS]
            
            # If they want ALL flavors, show more
            if "all" in text_lower or "tell me" in text_lower:
                flavors_str = ", ".join(flavor_list)
                speak(f"We have {flavors_str}. Which one would you like?")
            else:
                flavors_str = ", ".join(flavor_list[:5]) + ", and more"
                speak(f"We have {flavors_str}. Which one would you like?")
            return "CONTINUE"
        
        flavor = detect_pizza_flavor(user_text)
        if flavor:
            self.temp_item["name"] = flavor.title()
            self.state = OrderState.ASK_SIZE
            speak(f"{flavor.title()} pizza! Which size? Small, Regular, Medium, Large, or XXL?")
        else:
            # Use LLM for intelligent response
            # print("🤖 Using AI to understand...")
            context = f"Customer is choosing pizza flavor. Current state: Asking flavor."
            response, save_trigger = self.query_llm(user_text, context)
            speak(response)
        return "CONTINUE"
    
    def handle_ask_size(self, user_text):
        size = detect_pizza_size(user_text)
        if size:
            self.temp_item["size"] = size.title()
            self.current_order.append(self.temp_item.copy())
            
            qty = self.temp_item["quantity"]
            name = self.temp_item["name"]
            size_str = size.title()
            
            speak(f"Perfect! {qty} {size_str} {name} added. Anything else?")
            self.temp_item = {}
            self.state = OrderState.ASK_MORE
        else:
            # Use LLM for intelligent response
            # print("🤖 Using AI to understand size...")
            context = f"Customer is choosing pizza size. Available: Small, Regular, Medium, Large, XXL."
            response, save_trigger = self.query_llm(user_text, context)
            speak(response)
        return "CONTINUE"
    
    def handle_ask_more(self, user_text):
        text_lower = user_text.lower()
        
        if any(word in text_lower for word in ["no", "nope", "that's all", "thats all", "done", "finish", "nothing", "bas", "enough"]):
            self.state = OrderState.COLLECT_ADDRESS
            speak("Great! Now, please provide your full delivery address.")
            return "CONTINUE"
        elif is_pizza_request(text_lower):
            qty = extract_quantity(user_text)
            self.temp_item = {"quantity": qty, "category": "Pizza"}
            
            flavor = detect_pizza_flavor(user_text)
            if flavor:
                self.temp_item["name"] = flavor.title()
                self.state = OrderState.ASK_SIZE
                speak(f"{qty} {flavor.title()} pizza. Which size?")
            else:
                self.state = OrderState.ASK_FLAVOR
                speak(f"{qty} pizza. Which flavor?")
        else:
            # Use LLM for intelligent response
            # print("🤖 Using AI to understand...")
            context = f"Customer can add more items or finish order. Current items: {len(self.current_order)}"
            response, save_trigger = self.query_llm(user_text, context)
            speak(response)
            
            if save_trigger:
                if len(self.current_order) > 0:
                    pos_resp = send_to_pos({
                        "items": self.current_order,
                        "address": self.customer_address,
                        "phone": self.customer_phone
                    })
                    speak(f"Order saved by AI command. Order ID {pos_resp['order_id']}.")
                    return "EXIT"
                else:
                    speak("I can't save an empty order.")
        return "CONTINUE"
    
    def handle_collect_address(self, user_text):
        self.customer_address = user_text
        self.state = OrderState.COLLECT_PHONE
        speak("Got it! And your phone number please?")
        return "CONTINUE"
    
    def handle_collect_phone(self, user_text):
        # Extract phone number
        phone_match = re.search(r'\d{10,11}', user_text.replace(" ", ""))
        if phone_match:
            self.customer_phone = phone_match.group()
            self.state = OrderState.CONFIRM_ORDER
            
            # Show summary
            print("\n" + "="*60)
            print("📋 ORDER SUMMARY")
            print("="*60)
            for i, item in enumerate(self.current_order, 1):
                print(f"{i}. {item['quantity']}x {item['size']} {item['name']}")
            print(f"\nAddress: {self.customer_address}")
            print(f"Phone: {self.customer_phone}")
            print("="*60 + "\n")
            
            summary = ", ".join([f"{item['quantity']} {item['size']} {item['name']}" for item in self.current_order])
            speak(f"Let me confirm. {summary}. Delivering to {self.customer_address}. Phone {self.customer_phone}. Is this correct?")
        else:
            speak("I didn't catch the phone number. Please say it again?")
        return "CONTINUE"
    
    def handle_confirm_order(self, user_text):
        text_lower = user_text.lower()
        
        if "yes" in text_lower or "correct" in text_lower or "confirm" in text_lower:
            pos_resp = send_to_pos({
                "items": self.current_order,
                "address": self.customer_address,
                "phone": self.customer_phone
            })
            
            speak(f"Perfect! Your order {pos_resp['order_id']} is confirmed. Estimated delivery in 30-45 minutes. Thank you!")
            print(f"\n✅ Order {pos_resp['order_id']} saved successfully!")
            return "EXIT"
        else:
            speak("No problem. What would you like to change?")
            self.state = OrderState.ASK_MORE
        return "CONTINUE"

# -----------------------------
# MAIN FUNCTION
# -----------------------------
def main():
    order_system = OrderSystem()
    voice_mode = False  # Set to False for text-only mode
    
    speak("Hi! Welcome to our restaurant. What can I get you today?")
    
    while True:
        user_text = get_user_input(voice_mode)
        
        if not user_text:
            continue
        
        result = order_system.process_input(user_text)
        
        if result == "EXIT":
            break

if __name__ == "__main__":
    main()

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
import ast
from datetime import datetime

# -----------------------------
# CONFIG
# -----------------------------
OLLAMA_HOST = "http://localhost:11500"
MODEL = "llama3.1:8b"
MENU_FILE = "menu.xlsx"
USE_TTS = False
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
    
    # Fuzzy/Typo match FIRST (to catch 'extra large' before 'large')
    typo_map = {
        "smal": "small", "sml": "small",
        "reg": "regular", "normal": "regular",
        "med": "medium", "medum": "medium", 
        "larj": "large", "larg": "large", "lrg": "large",
        "xl": "xxl", "extra large": "xxl"
    }
    
    # Sort keys by length descending to match "extra large" before "large"
    sorted_typos = sorted(typo_map.keys(), key=len, reverse=True)
    
    for typo in sorted_typos:
        if typo in text_lower:
            return typo_map[typo]

    # Direct match
    for size in PIZZA_SIZES:
        if size in text_lower:
            return size
            
    return None

def is_pizza_request(text):
    text_lower = text.lower()
    pizza_keywords = ["pizza", "pie", "piza", "picza", "pizz", "slice"]
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
# VALIDATION HELPERS
# -----------------------------
def is_valid_address(address):
    return address and len(address) >= 5 and "..." not in address

def is_valid_phone(phone):
    return phone and len(phone) >= 9 and any(c.isdigit() for c in phone)

# -----------------------------
# POS API
# -----------------------------
def validate_order(order):
    """Validate order details before sending to POS"""
    missing = []
    
    # Validate Items
    if not order.get("items") or len(order["items"]) == 0:
        missing.append("items")
    else:
        for i, item in enumerate(order["items"]):
            if item.get("size") in ["...", "", None]:
                missing.append(f"size for item {i+1}")
            if item.get("name") in ["...", "", None]:
                missing.append(f"name for item {i+1}")
                
    # Validate Address
    if not is_valid_address(order.get("address", "")):
        missing.append("valid address")
        
    # Validate Phone
    if not is_valid_phone(order.get("phone", "")):
        missing.append("valid phone number")
        
    if missing:
        return False, f"Missing details: {', '.join(missing)}"
    return True, "Valid"

def send_to_pos(order):
    # Validation Step
    is_valid, msg = validate_order(order)
    if not is_valid:
        print(f"❌ Order validation failed: {msg}")
        return {"status": "error", "message": msg}

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
4. Do NOT use `[SAVE_ORDER]` or say "Order Confirmed" if you don't have the address and phone.
5. If STATUS says MISSING DETAILS, you MUST ask for them. NEVER successfully confirm.
6. NEVER use placeholders like "..." in tools. Ask the user if you don't know and wait for their response.
6. Example: "Got it! [SET_DETAILS: {{"address": "123 Main", "phone": "555"}}] Confirm order?"

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
        # Inject current order state into context
        order_summary = "Empty"
        if self.current_order:
            order_summary = ", ".join([f"{item['quantity']}x {item['size']} {item['name']}" for item in self.current_order])
        
        full_context = f"Current Order Cart: [{order_summary}]. "
        
        missing = []
        if not is_valid_address(self.customer_address): missing.append("Address")
        if not is_valid_phone(self.customer_phone): missing.append("Phone")
        
        if self.customer_address:
            full_context += f"Address: {self.customer_address}. "
        else:
            full_context += "Address: NOT PROVIDED. "
            
        if self.customer_phone:
            full_context += f"Phone: {self.customer_phone}. "
        else:
            full_context += "Phone: NOT PROVIDED. "
            
        if missing:
             full_context += f"STATUS: MISSING DETAILS ({', '.join(missing)}). DO NOT CONFIRM ORDER. ASK FOR MISSING DETAILS."
        else:
             full_context += "STATUS: ALL DETAILS PRESENT. READY TO CONFIRM."
        
        full_context += " " + context
        
        # Reinforce tool usage if we are building an order
        if self.temp_item or self.state in [OrderState.ASK_FLAVOR, OrderState.ASK_SIZE, OrderState.ASK_ITEM]:
             full_context += " IMPORTANT: If the user provided item details (name/size/quantity), you MUST use the `[ADD_ITEM]` tool in your response. Do not just blindly acknowledge."
        
        self.add_user_message(user_text, full_context)
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
                raw_json = add_item_match.group(1)
                try:
                    item_data = json.loads(raw_json)
                except:
                    item_data = ast.literal_eval(raw_json)
                
                # Check for incomplete data (Ellipsis or placeholders)
                # Note: valid quantity is int. valid size/name are strings not containing "..."
                
                is_incomplete = False
                
                # Clean up Quantity
                if item_data.get("quantity") is Ellipsis or str(item_data.get("quantity")) == "...":
                    item_data["quantity"] = 1
                
                # Clean up Name/Size and detect incompleteness
                for field in ["name", "size"]:
                    val = item_data.get(field)
                    if val is Ellipsis or val is None or "..." in str(val) or val == "":
                        if field == "size": # Size is allowed to be missing (we will ask for it)
                            item_data[field] = None 
                            is_incomplete = True
                        elif field == "name": # Name must be present generally, but if missing we can ask
                             item_data[field] = None
                             is_incomplete = True

                if is_incomplete:
                     # If incomplete, we store in temp_item to trigger state machine follow-up
                     # But only if we have at least a name or category (which isn't in this dict usually)
                     if item_data.get("name"):
                         self.temp_item = item_data
                         self.state = OrderState.ASK_SIZE
                         print(f"🔄 Partial item detected, waiting for details: {item_data}")
                     else:
                         print("⚠️ Ignored item with no name.")
                else:
                    self.current_order.append(item_data)
                    print(f"📦 Added item: {item_data}")
            except Exception as e:
                print(f"x Failed to parse item: {e}")
                print(f"   Raw content: {add_item_match.group(1)}")
        
        # Parse SET_DETAILS
        details_match = re.search(r'\[SET_DETAILS: ({.*?})\]', response)
        if details_match:
            try:
                raw_json = details_match.group(1)
                try:
                    details = json.loads(raw_json)
                except:
                    details = ast.literal_eval(raw_json)
                
                if "address" in details: self.customer_address = details["address"]
                if "phone" in details: self.customer_phone = details["phone"]
                print(f"📝 Details set: {details}")
            except Exception as e:
                print(f"❌ Failed to parse details: {e}")
                print(f"   Raw content: {details_match.group(1)}")
                
        # Parse SAVE_ORDER
        if "[SAVE_ORDER]" in response:
            if self.current_order and self.customer_address and self.customer_phone:
                pos_resp = send_to_pos({
                    "items": self.current_order,
                    "address": self.customer_address,
                    "phone": self.customer_phone
                })
                if pos_resp["status"] == "success":
                    speak(f"Order {pos_resp['order_id']} placed successfully!")
                    time.sleep(1)
                    sys.exit(0) # Exit after saving
                else:
                    speak(f"I cannot save the order yet. {pos_resp['message']}")
            else:
                print("❌ Missing details, cannot save yet.")

    def get_order_summary_text(self):
        if not self.current_order:
            return "You haven't ordered anything yet."
        summary = ", ".join([f"{item['quantity']} {item['size']} {item['name']}" for item in self.current_order])
        return f"You have ordered: {summary}."

    def check_order_inquiry(self, text_lower):
        inquiry_keywords = ["what i ordered", "my order", "cart", "basket", "what did i order", "what have i ordered", "check order"]
        if any(k in text_lower for k in inquiry_keywords):
            speak(self.get_order_summary_text())
            return True
        return False
        
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
        
        if self.check_order_inquiry(text_lower):
            return "CONTINUE"
        

    def is_menu_inquiry(self, text):
        text_lower = text.lower()
        # Use word boundaries for short keywords like "list", "have", "all", "what"
        # Longer keywords like "menu" are safer but consistent to use boundaries or specific checks
        
        # Regex for strict keyword matching
        keywords = r"\b(list|menu|have|available|options|flavors|flavours|all|tell me)\b"
        if re.search(keywords, text_lower):
            return True
            
        # Specific combination check for "what" (e.g. "what do you have" vs "what is your name")
        # "what" by itself is too broad, handled by specific logic in callers usually, 
        # but here we can check "what" + "menu"/"have" intersection if needed.
        # Original logic was: if "what" in text and "menu" in text: keywords.append("what")
        # Let's simplify: if they say "what", we only count it if "menu" or "have" is also there.
        
        if re.search(r"\bwhat\b", text_lower) and re.search(r"\b(menu|have|available)\b", text_lower):
            return True
            
        return False

    def handle_greeting(self, user_text):
        text_lower = user_text.lower()
        
        if self.check_order_inquiry(text_lower):
            return "CONTINUE"
        
        # Check if asking for menu first
        if self.is_menu_inquiry(user_text):
            flavor_list = [flavor.title() for flavor in PIZZA_FLAVORS]
            
            # If they want ALL flavors
            if re.search(r"\b(all|tell me all)\b", text_lower):
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
        
        if self.check_order_inquiry(text_lower):
            return "CONTINUE"
        
        # Check for menu inquiry
        if self.is_menu_inquiry(user_text):
            flavor_list = [flavor.title() for flavor in PIZZA_FLAVORS]
            
            if re.search(r"\b(all|tell me all)\b", text_lower):
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
        
        if self.check_order_inquiry(text_lower):
            return "CONTINUE"
        
        # Check if asking for menu/flavors list
        if self.is_menu_inquiry(user_text):
            # List all pizza flavors
            flavor_list = [flavor.title() for flavor in PIZZA_FLAVORS]
            
            # If they want ALL flavors, show more
            if re.search(r"\b(all|tell me)\b", text_lower):
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
            # Ensure we don't fall back to endless flavor loop if size is misunderstood
            context = f"Customer is choosing pizza size. Available: Small, Regular, Medium, Large, XXL."
            response, save_trigger = self.query_llm(user_text, context)
            speak(response)
        return "CONTINUE"
    
    def handle_ask_more(self, user_text):
        text_lower = user_text.lower()
        
        if any(word in text_lower for word in ["no", "nope", "that's all", "thats all", "done", "finish", "nothing", "bas", "enough"]):
            # Check if we have valid details to skip collection
            if not is_valid_address(self.customer_address):
                self.state = OrderState.COLLECT_ADDRESS
                speak("Great! Now, please provide your full delivery address.")
            elif not is_valid_phone(self.customer_phone):
                self.state = OrderState.COLLECT_PHONE
                speak("Got the address. And your phone number please?")
            else:
                # All details present, go straight to confirm
                self.state = OrderState.CONFIRM_ORDER
                self.handle_collect_phone(self.customer_phone) # Reuse summary logic
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
                    if pos_resp["status"] == "success":
                        speak(f"Order saved by AI command. Order ID {pos_resp['order_id']}.")
                        return "EXIT"
                    else:
                        speak(f"Could not save order. {pos_resp['message']}")
                        return "CONTINUE"
                else:
                    speak("I can't save an empty order.")
        return "CONTINUE"
    
    def handle_collect_address(self, user_text):
        self.customer_address = user_text
        self.state = OrderState.COLLECT_PHONE
        speak("Got it! And your phone number please?")
        return "CONTINUE"
    
    def handle_collect_phone(self, user_text):
        # Extract phone number - update regex for 9-15 digits
        phone_match = re.search(r'\d{9,15}', user_text.replace(" ", "").replace("-", ""))
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
            
            if pos_resp["status"] == "success":
                speak(f"Perfect! Your order {pos_resp['order_id']} is confirmed. Estimated delivery in 30-45 minutes. Thank you!")
                print(f"\n✅ Order {pos_resp['order_id']} saved successfully!")
                return "EXIT"
            else:
                speak(f"I can't confirm yet. {pos_resp['message']}")
                # If validation fails, stay in proper state to collect missing info
                # Here we just go back to asking if they want to change anything or provide info
                if "address" in pos_resp["message"] or "phone" in pos_resp["message"]:
                     self.state = OrderState.COLLECT_ADDRESS if "address" in pos_resp["message"] else OrderState.COLLECT_PHONE

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
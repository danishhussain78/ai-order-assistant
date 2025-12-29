import json
import requests
import speech_recognition as sr
import pyttsx3
import sys
import re
import time
from datetime import datetime
import os
import random

# -----------------------------
# CONFIG
# -----------------------------
OLLAMA_HOST = "http://localhost:11500"
MODEL = "llama3.2:3b"
MENU_FILE = "menu.txt"
USE_TTS = True
ORDERS_FILE = "orders.json"
LAST_ORDER_FILE = "last_order.json"
MAX_MEMORY = 20
MODE = "text"  # "voice" or "text"

# -----------------------------
# TTS SETUP
# -----------------------------
engine = pyttsx3.init()
voices = engine.getProperty('voices')
try:
    engine.setProperty('voice', voices[0].id)
except Exception:
    pass
engine.setProperty('rate', 160)

def clean_tts_text(text):
    if not text: return ""
    text = text.encode("ascii","ignore").decode()
    text = re.sub(r'[*_`~#]','',text)
    text = text.replace('\n',' ').replace('\r',' ').replace('\t',' ')
    text = re.sub(r'\s+',' ',text)
    return text.strip()

def speak(text):
    text = clean_tts_text(text)
    print(f"AI: {text}")
    if USE_TTS:
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"⚠️ TTS error: {e}")

# -----------------------------
# LOAD MENU FROM menu.txt
# -----------------------------
def load_menu(file_path):
    if not os.path.exists(file_path):
        print(f"⚠️ Menu file missing. Creating sample menu at {file_path}")
        sample_menu = [
            "Pizza Sizes: Small, Medium, Large, XXL",
            "Pizza Flavors: Chicken Surprise, Jamaican BBQ, Chicago Bold Fold",
            "Sides / Snacks: Garlic Bread, Chicken Wings",
            "Desserts: Chocolate Brownie, Ice Cream",
            "Beverages: Coke, Sprite, Water"
        ]
        with open(file_path, "w", encoding="utf-8") as f:
            for line in sample_menu:
                f.write(line + "\n")

    menu_dict = {}
    pizza_sizes = []
    menu_items_flat = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if ":" not in line:
                continue
            cat, items = line.strip().split(":", 1)
            cat = cat.strip()
            items_list = [i.strip() for i in items.split(",") if i.strip()]
            if cat.lower() == "pizza sizes":
                pizza_sizes = [i.strip() for i in items_list]
            else:
                menu_dict[cat] = items_list
                menu_items_flat.extend([i.lower() for i in items_list])
    return menu_dict, menu_items_flat, pizza_sizes

MENU, MENU_ITEMS_FLAT, PIZZA_SIZES = load_menu(MENU_FILE)

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
        try:
            r.adjust_for_ambient_noise(source,duration=0.3)
            audio = r.listen(source,timeout=5,phrase_time_limit=10)
            print("🔄 Processing...")
        except sr.WaitTimeoutError:
            print("❌ No speech detected")
            return None
    try:
        text = r.recognize_google(audio, language='en-IN')
        print(f"✅ You said: {text}")
        return text
    except Exception as e:
        print(f"❌ STT error: {e}")
        return None

# -----------------------------
# LLM CALL
# -----------------------------
SYSTEM_PROMPT = """
You are an expert human-like order taker on a phone call for home delivery.

Your job:
- Take the customer’s order.
- Confirm every item.
- After customer says “done” or “that’s all”, you MUST:
    1. Confirm the complete order.
    2. Ask for full address.
    3. Ask for street number.
    4. Ask for house number / apartment / floor.
    5. Ask for nearby landmark.
    6. Ask for phone number.
    7. Confirm all details and tell estimated delivery time.

────────────────────────────────────────
### HARD RULES (NEVER BREAK)
1. Only mention items that exist in the menu below.
2. Never invent new items, toppings, sizes, or flavors.
3. If customer asks “what do you have”, reply ONLY with item names, NOT categories.
4. If customer names something not in the menu:
     → “Sorry, we don’t have that. Please choose from our menu.”
5. For pizza flavors → always ask for size.
6. Allowed sizes are exactly:
     Small / Regular, Medium, Large, XXL slice / half / full
7. Keep responses short, friendly, natural.
8. Never ask for address until order is finished.
9. Never mention you are AI or a bot.

────────────────────────────────────────
### SPEAKING STYLE
- Human-like, natural, a bit Hinglish/Pakistani call center style.
- Short sentences (max 12–15 words).
- Polite confirmation after each step.
- Examples:
    - “Sure ji, which flavor?”
    - “Size bata dain please?”
    - “Done. Anything else?”
    - “Order complete? Should I confirm?”

────────────────────────────────────────
### MENU (ONLY THESE ITEMS ARE ALLOWED)

[PIZZA FLAVORS]
- Chicken Surprise
- Jamaican BBQ
- Chicago Bold Fold
- Phantom
- Dancing Fajita
- Tarzan Tikka
- West Side Garlic
- Mamma Mia Classic
- Godspell Beef Load
- Mughlai Beast
- Gypsy Euro
- Wicked Blend
- Arabic Ranch Pizza
- All Cheese
- All Veggie

[PIZZA SIZES]
- Regular / Small
- Medium
- Large
- XXL (slice / half / full)

────────────────────────────────────────

Always follow the rules above exactly.

"""

def call_llm(user_message, context=""):
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{context}\nCustomer: {user_message}"}
        ]

        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_predict": 100,
                "top_p": 0.9,
                "repeat_penalty": 1.2
            }
        }

        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        response = data.get("message", {}).get("content", "") or ""
        response_clean = response.strip()
        if not response_clean:
            return "Sorry, could you repeat that?"
        return response_clean

    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return "Sorry, could you repeat that?"

# -----------------------------
# ORDER HELPERS
# -----------------------------
def extract_quantity(text):
    number_words = {'one':1,'ek':1,'two':2,'do':2,'three':3,'teen':3,'four':4,'char':4,
                    'five':5,'panch':5,'six':6,'chay':6,'seven':7,'saat':7,'eight':8,'aath':8,
                    'nine':9,'nau':9,'ten':10,'dos':10,'das':10}
    if not text: return 1
    text_lower = text.lower()
    match = re.search(r'\b(\d{1,2})\b',text_lower)
    if match: return int(match.group(1))
    for word,num in number_words.items():
        if re.search(r'\b'+re.escape(word)+r'\b',text_lower): return num
    return 1

def extract_size(text):
    if not text:
        return None
    text_lower = text.lower()
    for sz in PIZZA_SIZES:
        # Split options like "Regular / Small"
        options = [s.strip().lower() for s in sz.split('/')]
        for opt in options:
            if re.search(r'\b' + re.escape(opt) + r'\b', text_lower):
                return sz  # Return menu-exact size
    return None


def parse_order_items(user_text, menu):
    items_found = []
    if not user_text: return items_found
    text_lower = user_text.lower()
    flat_items = []
    for cat, items in menu.items():
        for it in items:
            flat_items.append((it, cat))
    flat_items.sort(key=lambda x:-len(x[0]))
    for item_name, cat in flat_items:
        if item_name.lower() in text_lower:
            qty = extract_quantity(user_text)
            size = extract_size(user_text) if "pizza" in cat.lower() else None
            items_found.append({"category":cat,"name":item_name,"quantity":qty,"size":size})
            text_lower = text_lower.replace(item_name.lower()," ")
    return items_found

def save_order_to_file(order_data):
    try:
        orders=[]
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE,'r',encoding='utf-8') as f:
                try: orders=json.load(f)
                except: orders=[]
        orders.append(order_data)
        with open(ORDERS_FILE,'w',encoding='utf-8') as f:
            json.dump(orders,f,indent=2,ensure_ascii=False)
        with open(LAST_ORDER_FILE,'w',encoding='utf-8') as f:
            json.dump(order_data,f,indent=2,ensure_ascii=False)
        print(f"✅ Order saved to {ORDERS_FILE} and last order remembered")
        return True
    except Exception as e:
        print(f"❌ Failed to save order: {e}")
        return False

# -----------------------------
# ORDER STATE
# -----------------------------
class OrderState:
    GREETING = "greeting"
    TAKING_ORDER = "taking_order"
    CONFIRM_ITEMS = "confirm_items"
    GET_ADDRESS = "get_address"
    GET_STREET = "get_street"
    GET_HOUSE = "get_house"
    GET_LANDMARK = "get_landmark"
    GET_PHONE = "get_phone"
    CONFIRM_ORDER = "confirm_order"
    COMPLETE = "complete"

class OrderTaker:
    def __init__(self):
        self.state = OrderState.GREETING
        self.current_order=[]
        self.customer_info={"address":None,"street":None,"house":None,"landmark":None,"phone":None}
        self.conversation_memory=[]
        self.waiting_for_flavor = None
        self.waiting_for_size_item=None
        self.waiting_for_special=None

    def add_to_memory(self, role, content):
        self.conversation_memory.append({"role":role,"content":content})
        if len(self.conversation_memory) > MAX_MEMORY:
            self.conversation_memory = self.conversation_memory[-MAX_MEMORY:]

    def process_input(self, user_text):
        if not user_text: return "continue"
        if any(word in user_text.lower() for word in ["cancel","exit","quit","terminate"]):
            speak("Order cancelled. Thank you!")
            return "exit"
        if self.state==OrderState.GREETING: return self.handle_greeting(user_text)
        if self.state==OrderState.TAKING_ORDER: return self.handle_taking_order(user_text)
        if self.state==OrderState.CONFIRM_ITEMS: return self.show_order_summary()
        return "continue"

    def handle_greeting(self,user_text):
        self.add_to_memory("user",user_text)
        self.state=OrderState.TAKING_ORDER
        if os.path.exists(LAST_ORDER_FILE):
            with open(LAST_ORDER_FILE,'r',encoding='utf-8') as f:
                last=json.load(f)
                if last.get("items"):
                    items_str = ", ".join([f"{i['quantity']} {i.get('size','')} {i['name']}".strip() for i in last["items"]])
                    speak(f"Would you like to repeat your last order: {items_str}?")
        return self.handle_taking_order(user_text)

    def handle_taking_order(self, user_text):
        self.add_to_memory("user", user_text)
        user_text_clean = re.sub(r'[^a-zA-Z0-9 ]','',user_text.lower()).strip()

        # MENU REQUEST
        if "menu" in user_text_clean:
            menu_flavors = ", ".join(MENU.get("Pizza Flavors", []))
            speak(f"Our pizza flavors: {menu_flavors}")
            return "continue"

        # WAITING FOR FLAVOR
        if getattr(self, "waiting_for_flavor", None):
            flavor = None
            for f in MENU.get("Pizza Flavors", []):
                if f.lower() == user_text_clean:
                    flavor = f
                    break
            if flavor:
                self.waiting_for_size_item = {
                    "name": flavor,
                    "category": "Pizza Flavors",
                    "quantity": extract_quantity(user_text),
                }
                self.waiting_for_flavor = None
                speak(f"{flavor} flavor. Size bata dain please? Small, Medium, Large, or XXL?")
            else:
                speak("Sorry, we don't have that flavor. Please choose from our menu.")
            return "continue"

        # WAITING FOR SIZE
        if getattr(self, "waiting_for_size_item", None):
            size = extract_size(user_text)
            if size:
                self.waiting_for_size_item["size"] = size
                # Move to special request step
                self.waiting_for_special = self.waiting_for_size_item
                self.waiting_for_size_item = None
                speak("Koi special request? (e.g., no mayo, extra cheese) or say 'no'")
            else:
                sizes_str = ", ".join(PIZZA_SIZES)
                speak(f"Size bata dain please? {sizes_str}?")
            return "continue"


        # WAITING FOR SPECIAL
        if getattr(self, "waiting_for_special", None):
            special = user_text.strip()
            if special.lower() not in ["no", "none", "nothing"]:
                self.waiting_for_special["special_request"] = special
            else:
                self.waiting_for_special["special_request"] = ""
            # Add to current order
            self.current_order.append(self.waiting_for_special)
            size_str = f"{self.waiting_for_special.get('size', '')} " if self.waiting_for_special.get("size") else ""
            special_str = f" ({self.waiting_for_special.get('special_request')})" if self.waiting_for_special.get("special_request") else ""
            speak(f"Added {self.waiting_for_special['quantity']} {size_str}{self.waiting_for_special['name']}{special_str}. Anything else?")
            self.waiting_for_special = None
            return "continue"

        # USER SAYS "PIZZA"
        if "pizza" in user_text_clean:
            self.waiting_for_flavor = {}
            speak("One pizza, bata flavor please?")
            return "continue"

        # USER SAYS DONE
        if any(word in user_text_clean for word in ["done", "bas", "that's all", "finished", "finish", "no more", "nothing else"]):
            if self.current_order:
                self.state = OrderState.CONFIRM_ITEMS
                return self.show_order_summary()
            else:
                speak("You haven't ordered anything yet. What would you like?")
                return "continue"

        # OTHER MENU ITEMS
        found_items = parse_order_items(user_text, MENU)
        if found_items:
            for item in found_items:
                self.current_order.append(item)
            items_str = ", ".join([f"{i['quantity']} {i.get('size','') + ' ' if i.get('size') else ''}{i['name']}".strip() for i in found_items])
            speak(f"Okay, added {items_str}. Anything else?")
            return "continue"

        # FALLBACK LLM
        context = f"Customer said: {user_text}\nCurrent order items count: {len(self.current_order)}"
        response = call_llm(user_text, context)
        self.add_to_memory("assistant", response)
        speak(response)
        return "continue"

    def show_order_summary(self):
        summary_parts=[]
        for item in self.current_order:
            size_str=item.get('size','')
            special_str=item.get('special_request','')
            text = f"{item['quantity']} {size_str} {item['name']} {special_str}".strip()
            summary_parts.append(text)
        summary=", ".join(summary_parts)
        speak(f"Your order: {summary}. Is this correct?")
        return "continue"

# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    order_taker=OrderTaker()
    speak("Hello! Welcome to our restaurant. How may I help you today?")
    while True:
        if MODE=="voice":
            user_text=transcribe_microphone()
            if user_text is None:
                speak("Sorry, I couldn't hear you. Could you repeat that?")
                continue
        else:
            user_text=input("\nYou: ").strip()
        if not user_text: continue
        result=order_taker.process_input(user_text)
        if result in ["exit","complete"]: break
        time.sleep(0.25)
    print("\n✅ Session ended.")

if __name__=="__main__":
    main()

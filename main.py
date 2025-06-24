import time
import requests
import json # Import the json library
import logging
import random
import os # For environment variables
import asyncio # Import asyncio
import re # Import regular expressions
from telegram import Bot
from telegram.error import TelegramError # Correct import for error handling

# --- Configuration ---
# URL of the API endpoint to check
# IMPORTANT: Replace {some_id_I_have} with the actual ID if it's static,
# or ensure your environment provides it if it's dynamic. The {event_id} placeholder
# will be replaced by each ID from the EVENT_IDS list.
API_URL_TEMPLATE = "https://availability.ticketmaster.es/api/v2/TM_ES/resale/{event_id}"  # <<< VERIFY THIS TEMPLATE
# List of Event IDs to check. You can add as many IDs as you need.
EVENT_IDS = ["417009905","1848567714", "1589736692", "961888291", "1852247887", "1341715816", "412370092", "2035589996", "1378879656", "1566404077"] # <<< ADD YOUR EVENT IDS HERE
# Corresponding dates for each Event ID. MUST match the order and count of EVENT_IDS.
EVENT_DATES = ['30/05/26', '31/05/26', '02/06/26', '03/06/26', '06/06/26', '07/06/26', '10/06/26', '11/06/26', '14/06/26', '15/06/26'] # <<< DATES CORRESPONDING TO EVENT_IDS
# The JSON structure representing an "empty" response (no data)
EMPTY_RESPONSE = {"groups": [], "offers": []}  # <<< ADJUST IF THE EMPTY RESPONSE IS DIFFERENT
# How often to check the API, in seconds
CHECK_INTERVAL_SECONDS = 45  # <<< YOU CAN CHANGE THIS
# Minimum and maximum delay (in seconds) to add *before* each request
MIN_DELAY = 2
MAX_DELAY = 9
# Maximum price for an offer to be considered for notification
MAX_PRICE_THRESHOLD = 250.00 # <<< SET YOUR DESIRED MAX PRICE HERE
SOURCES_DIR = "/app/sources" # Directory for images (pista.jpg, golden.jpg, 100.jpg, etc.)
# Telegram Configuration (to be set via environment variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# TELEGRAM_CHAT_IDS should be a comma-separated string of chat IDs, e.g., "123456789,987654321"
TELEGRAM_CHAT_IDS_STR = os.getenv("TELEGRAM_CHAT_IDS") 
# Path inside the container where the seen offers data will be stored.
SEEN_OFFERS_FILE_PATH = "/app/data/seen_offers.json" # Ensure /app/data is a mounted volume in Docker
seen_offer_ids = set()

# List of possible User-Agent strings to rotate through
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0'
]

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- Seen Offers Functions ---
def load_seen_offers():
    global seen_offer_ids
    try:
        if os.path.exists(SEEN_OFFERS_FILE_PATH):
            with open(SEEN_OFFERS_FILE_PATH, 'r') as f:
                loaded_ids = json.load(f)
                if isinstance(loaded_ids, list):
                    seen_offer_ids = set(loaded_ids)
                    logging.info(f"Loaded {len(seen_offer_ids)} seen offer IDs from {SEEN_OFFERS_FILE_PATH}")
                else:
                    logging.warning(f"Content of {SEEN_OFFERS_FILE_PATH} is not a list. Starting with empty set.")
                    seen_offer_ids = set()
        else:
            logging.info(f"{SEEN_OFFERS_FILE_PATH} not found. Starting with empty set of seen offers.")
            seen_offer_ids = set()
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {SEEN_OFFERS_FILE_PATH}. Starting with empty set.")
        seen_offer_ids = set()
    except Exception as e:
        logging.error(f"Error loading {SEEN_OFFERS_FILE_PATH}: {e}. Starting with empty set.")
        seen_offer_ids = set()

def save_seen_offers():
    global seen_offer_ids
    try:
        directory = os.path.dirname(SEEN_OFFERS_FILE_PATH)
        if not os.path.exists(directory):
            os.makedirs(directory) # Create the directory if it doesn't exist
        with open(SEEN_OFFERS_FILE_PATH, 'w') as f:
            json.dump(list(seen_offer_ids), f, indent=2) # Save as a list for readability
    except Exception as e:
        logging.error(f"Error saving {SEEN_OFFERS_FILE_PATH}: {e}")

# --- MarkdownV2 Escaping Function ---
def escape_markdown_v2(text):
    """Escapes special characters for Telegram MarkdownV2."""
    if not isinstance(text, str): # Ensure text is a string
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in text])

# --- Telegram Function ---
async def send_telegram_message_to_single_chat(bot_instance, chat_id, message_text, photo_path=None):
    """Sends a message (text or photo with caption) via Telegram to a single chat_id."""
    if not bot_instance or not chat_id:
        logging.error("Telegram bot or chat_id not configured. Cannot send message.")
        return False # Indicate failure
    try:
        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as photo_file:
                sent_message = await bot_instance.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=message_text,
                    parse_mode='MarkdownV2'
                )
            logging.info(f"Telegram API ACKNOWLEDGED sending PHOTO to Chat ID: {chat_id}. Message ID: {sent_message.message_id}, Caption: \"{sent_message.caption[:50].replace(chr(10), ' ')}...\"")
        else:
            if photo_path: # photo_path was given but file not found
                 logging.warning(f"Photo path {photo_path} provided but file not found. Sending text message instead.")
            sent_message = await bot_instance.send_message(chat_id=chat_id, text=message_text, parse_mode='MarkdownV2')
            logging.info(f"Telegram API ACKNOWLEDGED sending TEXT message to Chat ID: {chat_id}. Message ID: {sent_message.message_id}, Text: \"{sent_message.text[:50].replace(chr(10), ' ')}...\"")
        return True # Indicate success
    except TelegramError as e: # Specific Telegram error
        logging.error(f"TelegramError sending message to {chat_id}: {e.message}")
        # Check for common errors like bot blocked or chat not found
        error_str = str(e).lower()
        if "bot was blocked by the user" in error_str or "chat not found" in error_str:
            logging.warning(f"Bot may have been blocked or chat ID {chat_id} is invalid.")
        elif "group chat was upgraded to a supergroup chat" in error_str:
            logging.warning(f"Group chat {chat_id} was upgraded. New chat ID might be needed: {e.message}")
    except Exception as e: # Catch other potential errors during sending
        logging.error(f"Unexpected error sending Telegram message to {chat_id}: {e}")
    return False # Indicate failure

# --- API Check Function ---
async def check_api_for_event(bot_instance, telegram_chat_id_to_send, event_id, event_date_str):
    """
    Fetches data from the API endpoint for a specific event_id,
    parses the JSON response,
    and sends specific offer details via Telegram if found.
    """
    current_api_url = API_URL_TEMPLATE.format(event_id=event_id)
    try:
        # Construct a plausible referer URL to make the request look more legitimate
        referer_url = f"https://www.ticketmaster.es/event/{event_id}"
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Referer': referer_url,
            'Origin': 'https://www.ticketmaster.es',
            'DNT': '1', # Do Not Track header, common in browsers
        }

        # requests.get is a blocking call. In a fully async app, you'd use aiohttp or run this in an executor.
        response = requests.get(current_api_url, headers=headers, timeout=30)
        response.raise_for_status()

        try:
            data = response.json()
        except json.JSONDecodeError:
            logging.error(f"Failed to decode JSON response from {current_api_url}")
            logging.error(f"Response text: {response.text[:500]}...")
            return

        if data != EMPTY_RESPONSE:
            offers_data = data.get('offers')
            if isinstance(offers_data, list) and offers_data:
                for i, offer in enumerate(offers_data):
                    offer_type_description = offer.get('offerTypeDescription', 'N/A')
                    calculated_price_str = "N/A"
                    price_info = offer.get('price')
                    if price_info and 'total' in price_info:
                        try:
                            total_price_raw = price_info['total']
                            if isinstance(total_price_raw, (int, float)):
                                calculated_price_val = total_price_raw / 100
                                # Price condition check using the defined threshold
                                if calculated_price_val < MAX_PRICE_THRESHOLD:
                                    calculated_price_str = f"{calculated_price_val:.2f}"
                                else:
                                    logging.info(f"Offer price {calculated_price_val:.2f} for event {event_id} is >= 400.00. Skipping message.")
                                    continue # Skip to the next offer
                            else:
                                calculated_price_str = f"Invalid format ({total_price_raw})"
                                logging.warning(f"Price format invalid for offer in event {event_id}. Skipping message for this offer.")
                                continue # Skip to the next offer
                        except (ValueError, TypeError, KeyError) as e:
                            calculated_price_str = f"Error processing"
                            logging.error(f"Error processing price for offer in event {event_id}: {e}. Skipping message for this offer.")
                            continue # Skip to the next offer
                    else: # No price info or total
                        logging.warning(f"No price/total found for offer in event {event_id}. Skipping message for this offer.")
                        continue # Skip to the next offer
                    
                    # --- Check if offer has already been seen ---
                    current_offer_id = offer.get('id') # This is the unique ID for the offer
                    if current_offer_id and current_offer_id in seen_offer_ids:
                        logging.info(f"Offer ID {current_offer_id} for event {event_id} already seen. Skipping notification.")
                        continue # Skip to the next offer

                    # --- Extract Seat Information ---
                    seat_info_lines = []
                    offer_id_to_match = offer.get('id') # Use the 'id' from the offer, not 'listingId'
                    groups_data = data.get('groups', [])
                    
                    if offer_id_to_match:
                        for group in groups_data:
                            if offer_id_to_match in group.get('offerIds', []): # Match offer 'id' with 'offerIds' in group
                                places = group.get('places', {})
                                if places:
                                    # Assuming one place entry per matching group for simplicity, as per example
                                    for place_key, row_data in places.items(): # e.g., place_key = "M-217"
                                        # Extract sector: find the first digit and everything after that looks like part of an identifier
                                        match = re.search(r'\d[\d\w-]*', place_key)
                                        sector = match.group(0) if match else place_key # Fallback to full key if no numeric part found
                                        seat_info_lines.append(f"SECTOR: {sector}")
                                        if isinstance(row_data, dict):
                                            for row_num_str, seat_list in row_data.items(): # e.g., row_number = "4"
                                                seat_info_lines.append(f"FILA: {row_num_str}")
                                                if isinstance(seat_list, list) and seat_list:
                                                    # Join multiple seats if present, or take the first
                                                    raw_asientos_str = ", ".join(seat_list) # Not escaped here
                                                    seat_info_lines.append(f"ASIENTO: {raw_asientos_str}")
                                                break # Assuming one row per place for this offer
                                        break # Assuming one place structure per group for this offer
                                break # Found matching group

                    # Escape dynamic content for MarkdownV2
                    escaped_offer_type = escape_markdown_v2(offer_type_description)
                    escaped_date = escape_markdown_v2(event_date_str)
                    escaped_price = escape_markdown_v2(calculated_price_str)
                    event_link = f"https://www.ticketmaster.es/event/{event_id}"

                    # --- Determine Image to Send ---
                    image_to_send_path = None
                    offer_desc_lower = offer_type_description.lower()

                    # 1. Pista/Gold Check
                    if 'pista' in offer_desc_lower or 'floor' in offer_desc_lower:
                        pista_image_path = os.path.join(SOURCES_DIR, "pista.jpg")
                        if os.path.exists(pista_image_path):
                            image_to_send_path = pista_image_path
                        else:
                            logging.warning(f"{pista_image_path} not found.")
                    elif 'gold' in offer_desc_lower or 'golden' in offer_desc_lower:
                        golden_image_path = os.path.join(SOURCES_DIR, "golden.jpg")
                        if os.path.exists(golden_image_path):
                            image_to_send_path = golden_image_path
                        else:
                            logging.warning(f"{golden_image_path} not found.")

                    # 2. Sector Check (if no Pista/Gold match and sector info is available)
                    if not image_to_send_path and seat_info_lines:
                        extracted_sector_value_for_image = None
                        for line in seat_info_lines: # seat_info_lines contains raw, unescaped strings here
                            if line.startswith("SECTOR:"):
                                try:
                                    sector_part_str = line.split(":", 1)[1].strip()
                                    sector_digits_match = re.search(r'\d+', sector_part_str)
                                    if sector_digits_match:
                                        extracted_sector_value_for_image = int(sector_digits_match.group(0))
                                        break 
                                except (IndexError, ValueError) as e_parse:
                                    logging.warning(f"Could not parse sector for image from line '{line}': {e_parse}")
                        
                        if extracted_sector_value_for_image is not None:
                            candidate_image_numbers = []
                            if os.path.exists(SOURCES_DIR) and os.path.isdir(SOURCES_DIR):
                                for filename in os.listdir(SOURCES_DIR):
                                    if filename.lower().endswith(".jpg"):
                                        base_name = filename[:-4] 
                                        if base_name.isdigit():
                                            img_num = int(base_name)
                                            if img_num <= extracted_sector_value_for_image:
                                                candidate_image_numbers.append(img_num)
                            if candidate_image_numbers:
                                best_match_num = max(candidate_image_numbers)
                                potential_image_path = os.path.join(SOURCES_DIR, f"{best_match_num}.jpg")
                                if os.path.exists(potential_image_path):
                                    image_to_send_path = potential_image_path
                                else:
                                    logging.warning(f"Constructed sector image path {potential_image_path} does not exist.")
                            else:
                                logging.info(f"No suitable sector image (<= value) found for sector {extracted_sector_value_for_image} in {SOURCES_DIR}")
                        else:
                            logging.info(f"No Pista/Gold image match, and sector value not determined from seat_info for image lookup.")

                    # Construct the message header
                    header_line = f"*{escaped_offer_type}* [{escaped_date}]({event_link})" # Date as hyperlink

                    message_lines = [
                        header_line,
                        "" # Blank line
                    ]

                    if seat_info_lines:
                        message_lines.extend([escape_markdown_v2(line) for line in seat_info_lines]) # Escape each seat info line
                    
                    message_lines.append("") # Blank line
                    message_lines.append(f"*{escaped_price}€*")

                    message_to_send = "\n".join(message_lines)
                    
                    # Send to all configured chat IDs
                    any_message_sent_successfully = False
                    for chat_id_to_send_to in telegram_chat_id_to_send: # telegram_chat_id_to_send is now a list
                        if await send_telegram_message_to_single_chat(bot_instance, chat_id_to_send_to, message_to_send, photo_path=image_to_send_path):
                            any_message_sent_successfully = True
                    if any_message_sent_successfully and current_offer_id: # Only add to seen if sent to at least one
                        seen_offer_ids.add(current_offer_id)
                        save_seen_offers() # Save the updated list
                    
                    if len(offers_data) > 1 and i < len(offers_data) - 1:
                        await asyncio.sleep(1) # Use asyncio.sleep
            elif data != EMPTY_RESPONSE:
                logging.warning(f"Data found for event ID {event_id} (linked to date {event_date_str}), but no 'offers' array or it's empty. Raw data structure: {json.dumps(data)}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching {current_api_url}: {e}")
        logging.error(f"This was for event ID {event_id} (linked to date {event_date_str}).")
    except Exception as e:
        logging.error(f"An unexpected error occurred while processing event ID {event_id} (date {event_date_str}): {e}")

# --- Main Async Function ---
async def main():
    logging.info("Starting API checker script...")

    if not TELEGRAM_BOT_TOKEN:
        logging.error("CRITICAL: TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
        exit(1)
    if not TELEGRAM_CHAT_IDS_STR:
        logging.error("CRITICAL: TELEGRAM_CHAT_IDS environment variable not set. Exiting.")
        exit(1)
    
    # Parse the comma-separated chat IDs into a list
    telegram_chat_ids_list = [chat_id.strip() for chat_id in TELEGRAM_CHAT_IDS_STR.split(',') if chat_id.strip()]
    if not telegram_chat_ids_list:
        logging.error("CRITICAL: TELEGRAM_CHAT_IDS environment variable is set but contains no valid chat IDs after parsing. Exiting.")
        exit(1)
    logging.info(f"Target Telegram Chat IDs: {telegram_chat_ids_list}")

    if not EVENT_IDS or any(id_val in ["YOUR_EVENT_ID_1", "YOUR_EVENT_ID_2", "YOUR_EVENT_ID_3"] for id_val in EVENT_IDS):
        logging.warning("Please update the EVENT_IDS list with your actual event IDs.")
    logging.info(f"API URL Template: {API_URL_TEMPLATE}")
    if len(EVENT_IDS) != len(EVENT_DATES):
        logging.error("CRITICAL: The number of items in EVENT_IDS and EVENT_DATES does not match!")
        logging.error(f"EVENT_IDS has {len(EVENT_IDS)} items, EVENT_DATES has {len(EVENT_DATES)} items.")
        logging.error("Please ensure both lists have the same number of entries and correspond to each other. Exiting.")
        exit(1)
    logging.info(f"Event IDs to check: {EVENT_IDS}")
    logging.info(f"Looking for data different from: {json.dumps(EMPTY_RESPONSE)}")

    # Load seen offers at startup
    load_seen_offers()

    bot_instance = Bot(token=TELEGRAM_BOT_TOKEN)
    logging.info("Telegram Bot initialized.")

    # --- TEST MESSAGE ON STARTUP & LOG CREDENTIALS ---
    # Log the first few and last few characters of the token to verify it's loaded, but not the whole thing for security.
    token_preview = f"{TELEGRAM_BOT_TOKEN[:5]}...{TELEGRAM_BOT_TOKEN[-5:]}" if TELEGRAM_BOT_TOKEN and len(TELEGRAM_BOT_TOKEN) > 10 else "Token not loaded or too short"    
    logging.info(f"Script using Token (preview): {token_preview}")
    test_message_text = f"*Fan2Fan Bot Startup Test* `(async)`\nIf you see this, basic Telegram sending is working\nBot instance active: `{bot_instance is not None}`"
    logging.info(f"Attempting to send startup test message to: {telegram_chat_ids_list}")
    for chat_id_to_test in telegram_chat_ids_list:
        if await send_telegram_message_to_single_chat(bot_instance, chat_id_to_test, test_message_text):
            logging.info(f"Startup test message sent successfully to {chat_id_to_test}.")
    # --- END OF TEST MESSAGE ---

    while True:
        try:
            if not EVENT_IDS:
                logging.warning("EVENT_IDS list is empty. Nothing to check. Sleeping for interval.")
            else:
                for index, event_id in enumerate(EVENT_IDS):
                    event_date_str = EVENT_DATES[index]
                    random_request_delay = random.uniform(MIN_DELAY, MAX_DELAY)
                    await asyncio.sleep(random_request_delay) # Use asyncio.sleep
                    await check_api_for_event(bot_instance, telegram_chat_ids_list, event_id, event_date_str) # Pass the list of chat IDs
            await asyncio.sleep(CHECK_INTERVAL_SECONDS) # Use asyncio.sleep
        except KeyboardInterrupt:
            logging.info("Script interrupted by user. Exiting...")
            break
        except Exception as e:
            logging.error(f"An error occurred in the main loop: {e}")
            logging.info(f"Waiting for {CHECK_INTERVAL_SECONDS} seconds before retrying...")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS) # Use asyncio.sleep

# --- Entry Point ---
if __name__ == "__main__":
    asyncio.run(main())

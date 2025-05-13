import requests
import time
import json # Import the json library
import logging
import random
import os # For environment variables
from telegram import Bot
from telegram.error import TelegramError

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
CHECK_INTERVAL_SECONDS = 100  # <<< YOU CAN CHANGE THIS
# Minimum and maximum delay (in seconds) to add *before* each request
MIN_DELAY = 2
MAX_DELAY = 7
# Telegram Configuration (to be set via environment variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# List of possible User-Agent strings to rotate through
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0'
]

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- Telegram Function ---
def send_telegram_message(bot_instance, chat_id, message_text):
    """Sends a message via Telegram."""
    if not bot_instance or not chat_id:
        logging.error("Telegram bot or chat_id not configured. Cannot send message.")
        return
    try:
        bot_instance.send_message(chat_id=chat_id, text=message_text)
        logging.info(f"Successfully sent Telegram message to chat ID {chat_id}")
    except TelegramError as e:
        logging.error(f"TelegramError sending message to {chat_id}: {e.message}")
    except Exception as e:
        logging.error(f"Unexpected error sending Telegram message to {chat_id}: {e}")

# --- Main Function ---
def check_api_for_event(bot_instance, telegram_chat_id_to_send, event_id, event_date_str):
    """
    Fetches data from the API endpoint for a specific event_id,
    parses the JSON response,
    and sends specific offer details via Telegram if found.
    """
    current_api_url = API_URL_TEMPLATE.format(event_id=event_id)
    try:
        # Choose a random User-Agent and set standard headers for JSON request
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/plain, */*' # Standard accept header for APIs
            # Add any other specific headers identified from DevTools if needed:
            # 'Authorization': 'Bearer YOUR_TOKEN',
            # 'X-Requested-With': 'XMLHttpRequest',
        }
        # logging.info(f"Fetching {current_api_url} with User-Agent: {headers['User-Agent']}") # Reduced verbosity

        # Make the HTTP GET request to the API endpoint
        response = requests.get(current_api_url, headers=headers, timeout=30) # 30-second timeout

        # Check if the request was successful (status code 200)
        response.raise_for_status() # Raises an HTTPError for bad responses (4xx or 5xx)

        # Parse the JSON response
        try:
            data = response.json()
        except json.JSONDecodeError:
            logging.error(f"Failed to decode JSON response from {current_api_url}")
            logging.error(f"Response text: {response.text[:500]}...") # Log the first 500 chars
            return # Stop processing this check

        # Compare the received data with the known empty response
        if data != EMPTY_RESPONSE:
            # logging.info(f"FOUND NEW DATA for event ID {event_id}!") # Removed to make console output cleaner as per request

            offers_data = data.get('offers')
            if isinstance(offers_data, list) and offers_data:
                for i, offer in enumerate(offers_data):
                    offer_type_description = offer.get('offerTypeDescription', 'N/A')

                    calculated_price_str = "N/A" # Default if price cannot be determined
                    price_info = offer.get('price')
                    if price_info and 'total' in price_info:
                        try:
                            total_price_raw = price_info['total']
                            # Ensure total_price_raw is a number (int or float) before division
                            if isinstance(total_price_raw, (int, float)):
                                calculated_price_val = total_price_raw / 100
                                calculated_price_str = f"{calculated_price_val:.2f}"
                            else:
                                calculated_price_str = f"Invalid format ({total_price_raw})"
                        except (ValueError, TypeError, KeyError) as e:
                            calculated_price_str = f"Error processing"

                    message_lines = [
                        f"ENTRADA: {offer_type_description}",
                        f"DIA: {event_date_str}",
                        f"PRECIO: {calculated_price_str}.", # Kept the period as per previous request
                        f"LINK: https://a.com/b/{event_id}"
                    ]
                    message_to_send = "\n".join(message_lines)
                    send_telegram_message(bot_instance, telegram_chat_id_to_send, message_to_send)
                    
                    # Small delay between messages if multiple offers are found for the same event
                    if len(offers_data) > 1 and i < len(offers_data) - 1:
                        time.sleep(1) # 1-second delay to avoid rate limiting / message flood

            elif data != EMPTY_RESPONSE: # Data was found, but 'offers' part is missing or empty
                logging.warning(f"Data found for event ID {event_id} (linked to date {event_date_str}), but no 'offers' array or it's empty. Raw data structure: {json.dumps(data)}")

    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching {current_api_url}: {e}")
        logging.error(f"This was for event ID {event_id} (linked to date {event_date_str}).")
    except Exception as e:
        logging.error(f"An unexpected error occurred while processing event ID {event_id} (date {event_date_str}): {e}")

# --- Main Loop ---
if __name__ == "__main__":
    logging.info("Starting API checker script...")

    if not TELEGRAM_BOT_TOKEN:
        logging.error("CRITICAL: TELEGRAM_BOT_TOKEN environment variable not set. Exiting.")
        exit(1)
    if not TELEGRAM_CHAT_ID:
        logging.error("CRITICAL: TELEGRAM_CHAT_ID environment variable not set. Exiting.")
        exit(1)

    if not EVENT_IDS or any(id_val in ["YOUR_EVENT_ID_1", "YOUR_EVENT_ID_2", "YOUR_EVENT_ID_3"] for id_val in EVENT_IDS):
        logging.warning("Please update the EVENT_IDS list with your actual event IDs.")
    logging.info(f"API URL Template: {API_URL_TEMPLATE}")
    if len(EVENT_IDS) != len(EVENT_DATES):
        logging.error("CRITICAL: The number of items in EVENT_IDS and EVENT_DATES does not match!")
        logging.error(f"EVENT_IDS has {len(EVENT_IDS)} items, EVENT_DATES has {len(EVENT_DATES)} items.")
        logging.error("Please ensure both lists have the same number of entries and correspond to each other. Exiting.")
        exit(1) # Exit the script
    logging.info(f"Event IDs to check: {EVENT_IDS}")
    logging.info(f"Looking for data different from: {json.dumps(EMPTY_RESPONSE)}")
    # logging.info(f"Check interval (after all IDs are checked): {CHECK_INTERVAL_SECONDS} seconds") # Reduced verbosity
    # logging.info(f"Random delay between checks: {MIN_DELAY}-{MAX_DELAY} seconds") # Reduced verbosity

    bot_instance = Bot(token=TELEGRAM_BOT_TOKEN)
    logging.info("Telegram Bot initialized.")

    while True:
        try:
            if not EVENT_IDS:
                logging.warning("EVENT_IDS list is empty. Nothing to check. Sleeping for interval.")
            else:
                for index, event_id in enumerate(EVENT_IDS):
                    event_date_str = EVENT_DATES[index] # Get the corresponding date
                    # Add a random delay *before* each individual check to seem less robotic
                    random_request_delay = random.uniform(MIN_DELAY, MAX_DELAY)
                    # logging.info(f"Waiting for random request delay: {random_request_delay:.2f} seconds before checking ID {event_id}...") # Reduced verbosity
                    time.sleep(random_request_delay)

                    # Perform the check for the current event_id and its date, passing bot instance and chat ID
                    check_api_for_event(bot_instance, TELEGRAM_CHAT_ID, event_id, event_date_str)

            # logging.info(f"All event IDs processed. Waiting for main check interval: {CHECK_INTERVAL_SECONDS} seconds...") # Reduced verbosity
            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logging.info("Script interrupted by user. Exiting.")
            break
        except Exception as e:
            # Catch potential errors in the loop itself
            logging.error(f"Error in main loop: {e}")
            # Wait a bit before retrying to avoid spamming errors
            time.sleep(60)

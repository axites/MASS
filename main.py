import asyncio
import os
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    FloodWaitError as FloodWait,
    ChatSendMediaForbiddenError,
    ChatWriteForbiddenError,
    UserBannedInChannelError
)
from telethon.tl.functions.channels import GetFullChannelRequest

# === CONFIGURATION ===
# --- Basic Credentials ---
# Get these from my.telegram.org
api_id = 26761740
api_hash = '1b0e718db9b6f7257f47c1dc8900f6fc'
session_name = 'mass_dms' # Using a more descriptive session name
phone_number = "+6281370860685"
twofa_password = "Memek123" # Leave as "" if you don't have 2FA enabled

# --- Script Settings ---
# The channel you want to copy messages FROM
SOURCE_CHANNEL_ID = -1002523697666

# Delay in seconds between sending to each group to avoid spam flags
DELAY_PER_GROUP = 0.2

# How often the script runs the entire loop, in seconds (e.g., 5 * 60 = 5 minutes)
LOOP_INTERVAL = 5 * 60

# The minimum number of members a group must have to be considered a target
MIN_GROUP_MEMBERS = 1000

# Optional: Text to send if an attachment is blocked and the original message had no text.
# This applies to all file types (media, zip, txt, etc.).
# Leave as "" to simply skip these groups.
ATTACHMENT_FALLBACK_TEXT = "The original message contained an attachment that couldn't be sent here."

# --- Technical Settings ---
PARSE_MODE = 'markdown'

def log(msg):
    """Prints a message with a timestamp for better logging."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

async def auto_login(client):
    """
    Connects the client and handles the login process automatically,
    including phone code and 2FA password entry.
    """
    await client.connect()
    if not await client.is_user_authorized():
        log("Client not authorized. Starting login process...")
        try:
            await client.send_code_request(phone_number)
            # Prompt for the code in the console
            code = input("[?] Enter the login code sent to your Telegram: ")
            await client.sign_in(phone_number, code)
        except SessionPasswordNeededError:
            # If 2FA is enabled, sign in with the password
            log("Two-factor authentication is enabled. Signing in with password.")
            await client.sign_in(password=twofa_password)
        except PhoneCodeInvalidError:
            log("[X] ERROR: The login code you entered is invalid. Please restart the script.")
            exit(1) # Exit the script if the code is wrong
        except Exception as e:
            log(f"[X] ERROR during login: {e}")
            exit(1)
        log("✅  Login successful. Session file saved.")
    else:
        log("✅  Client is already authorized.")

async def main():
    """Main function to run the message forwarding loop."""
    client = TelegramClient(session_name, api_id, api_hash)
    await auto_login(client)

    while True:
        log("--- Starting new broadcast loop ---")

        # 1. Fetch the latest message from the source channel
        latest_message = None
        try:
            log(f"Fetching latest message from source channel ID: {SOURCE_CHANNEL_ID}...")
            messages = await client.get_messages(SOURCE_CHANNEL_ID, limit=1)
            if not messages:
                log("[-] No messages found in the source channel. Waiting for next loop.")
                await asyncio.sleep(LOOP_INTERVAL)
                continue
            latest_message = messages[0]
            log("✅  Successfully fetched the latest message.")
        except Exception as e:
            log(f"[X] ERROR: Could not fetch message from source channel: {e}")
            log("This could be due to an incorrect SOURCE_CHANNEL_ID or not being a member.")
            log("Waiting for the next loop to try again.")
            await asyncio.sleep(LOOP_INTERVAL)
            continue

        # 2. Iterate through your chats/dialogs to find target groups
        sent_count = 0
        failed_count = 0
        processed_groups = set() # Keep track of groups we've already tried in this loop
        log("Scanning dialogs for eligible groups...")
        async for dialog in client.iter_dialogs():
            if dialog.id in processed_groups:
                continue

            # Filter for large megagroups only
            if not dialog.is_group or not getattr(dialog.entity, 'megagroup', False):
                continue

            processed_groups.add(dialog.id)

            try:
                # Get full channel info to check member count
                full_channel_info = await client(GetFullChannelRequest(dialog.entity))
                members = full_channel_info.full_chat.participants_count

                # Skip small groups
                if members < MIN_GROUP_MEMBERS:
                    # This log is commented out to reduce noise, but you can enable it for debugging.
                    # log(f"[-] Skipping '{dialog.name}' (members: {members}) - below minimum of {MIN_GROUP_MEMBERS}.")
                    continue

                log(f"[+] Found eligible group: '{dialog.name}' ({members} members). Attempting to send...")

                # --- Main Sending Logic ---
                try:
                    # This is the key part. By passing the entire 'latest_message' object,
                    # Telethon automatically handles sending the message as it is,
                    # including text, captions, and ANY file attachment (media, zip, txt, csv, etc.).
                    await client.send_message(
                        entity=dialog.entity.id,
                        message=latest_message,
                        parse_mode=PARSE_MODE
                    )
                    log(f"--> SUCCESS: Message sent to '{dialog.name}'")
                    sent_count += 1
                    await asyncio.sleep(DELAY_PER_GROUP)

                except ChatSendMediaForbiddenError:
                    log(f"[!] Attachments (media/files) are forbidden in '{dialog.name}'. Attempting to send text only.")
                    
                    # Fallback to sending only the text part of the message
                    text_to_send = latest_message.text
                    
                    # If the original message had no text (e.g., just a file), use the fallback text
                    if not text_to_send and ATTACHMENT_FALLBACK_TEXT:
                        text_to_send = ATTACHMENT_FALLBACK_TEXT
                    
                    if text_to_send:
                        try:
                            await client.send_message(entity=dialog.entity.id, message=text_to_send, parse_mode=PARSE_MODE)
                            log(f"--> SUCCESS: Sent TEXT-ONLY to '{dialog.name}'")
                            sent_count += 1
                            await asyncio.sleep(DELAY_PER_GROUP)
                        except Exception as fallback_e:
                            log(f"[X] FAILED to send text-only fallback to '{dialog.name}': {fallback_e}")
                            failed_count += 1
                    else:
                        log(f"[-] SKIPPED '{dialog.name}' as attachments are forbidden and the message has no text.")

                except ChatWriteForbiddenError:
                    log(f"[X] FAILED: You do not have permission to write messages in '{dialog.name}'.")
                    failed_count += 1
                except UserBannedInChannelError:
                    log(f"[X] FAILED: You are banned from '{dialog.name}'.")
                    failed_count += 1
                except FloodWait as e:
                    log(f"[!] Flood wait error: sleeping for {e.seconds} seconds. Breaking inner loop.")
                    await asyncio.sleep(e.seconds)
                    break # Stop sending to groups for now and wait
                except Exception as e:
                    log(f"[X] FAILED to send to '{dialog.name}': {e}")
                    failed_count += 1
            except Exception as e:
                log(f"[X] Could not process group '{getattr(dialog, 'name', 'Unknown')}': {e}")
                failed_count += 1

        # 3. Check account status with @spambot
        try:
            log("Sending /start to @spambot to check account status...")
            await client.send_message('spambot', '/start')
            log("✅  /start command sent to @spambot.")
        except Exception as e:
            log(f"[!] Warning: Failed to message @spambot: {e}")

        # --- LOOP SUMMARY ---
        log("--- Loop Summary ---")
        log(f"Messages Sent Successfully: {sent_count}")
        log(f"Failed Attempts: {failed_count}")
        log(f"--------------------")
        log(f"Waiting for {LOOP_INTERVAL / 60:.1f} minutes before the next loop...")
        await asyncio.sleep(LOOP_INTERVAL)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("\nScript stopped by user. Exiting gracefully.")
    except Exception as e:
        log(f"\n[X] An unexpected critical error occurred: {e}")

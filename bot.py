import os
import tempfile
import asyncio
import time
import re
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables")

if not CHANNEL_USERNAME and not CHANNEL_ID:
    raise ValueError("CHANNEL_USERNAME or CHANNEL_ID must be set in environment variables")

# Normalize channel identifiers - strip "@" if present
if CHANNEL_USERNAME:
    CHANNEL_USERNAME = CHANNEL_USERNAME.lstrip('@')
    
# Process CHANNEL_ID
channel_id_numeric = None
if CHANNEL_ID:
    # Remove "@" if present
    CHANNEL_ID = CHANNEL_ID.lstrip('@')
    try:
        # Try to convert to int for numeric channel IDs
        channel_id_numeric = int(CHANNEL_ID)
    except ValueError:
        # If not numeric, it's a username - use CHANNEL_USERNAME instead
        if not CHANNEL_USERNAME:
            CHANNEL_USERNAME = CHANNEL_ID
        CHANNEL_ID = None

# Determine channel identifier for API calls
# Use numeric CHANNEL_ID if available, otherwise use CHANNEL_USERNAME with @ prefix
if channel_id_numeric:
    CHANNEL = channel_id_numeric
elif CHANNEL_USERNAME:
    CHANNEL = f"@{CHANNEL_USERNAME}"
else:
    raise ValueError("CHANNEL_USERNAME or valid numeric CHANNEL_ID must be set")

# User language preferences (user_id -> language)
user_languages = {}

# Translation dictionaries
TRANSLATIONS = {
    'en': {
        'select_language': 'Please select your language / لطفا زبان خود را انتخاب کنید',
        'hello': 'Hello {name}! 👋',
        'already_member': "You're already a member! 🎉",
        'send_link': 'Send me a SoundCloud link to download the track.',
        'join_channel_first': 'To use this bot, you need to join our channel first.',
        'join_and_click': "Please join the channel and click 'I Joined' button below.",
        'join_channel': 'Join Channel',
        'i_joined': '✅ I Joined',
        'verified': "Great! ✅ You're verified!",
        'not_joined': "❌ You haven't joined the channel yet.",
        'join_first_then_click': "Please join the channel first and then click 'I Joined' button.",
        'need_join': "❌ You need to join the channel first to use this bot.",
        'invalid_link': 'Please send me a valid SoundCloud link.',
        'link_example': 'Example: https://soundcloud.com/artist/track-name',
        'downloading': '⏳ Downloading track... Please wait.',
        'download_failed': "❌ Failed to download the track.",
        'link_check': 'Please make sure the link is valid and the track is publicly available.',
        'success': '✅ Track downloaded and sent successfully!',
        'send_failed': "❌ Failed to send the audio file.",
        'downloaded_not_sent': 'The file was downloaded but couldn\'t be sent. Please try again.',
        'error_occurred': "❌ An error occurred while processing your request.",
        'try_again': 'Please try again later or check if the link is valid.',
    },
    'fa': {
        'select_language': 'لطفا زبان خود را انتخاب کنید / Please select your language',
        'hello': 'سلام {name}! 👋',
        'already_member': '',
        'send_link': 'لینک SoundCloud را برای دانلود آهنگ ارسال کنید.',
        'join_channel_first': 'برای استفاده از این ربات، ابتدا باید به کانال ما بپیوندید.',
        'join_and_click': 'لطفاً به کانال بپیوندید و دکمه "من پیوستم" را کلیک کنید.',
        'join_channel': 'عضویت در کانال',
        'i_joined': '✅ من پیوستم',
        'verified': 'عالی! ✅ شما تأیید شدید!',
        'not_joined': '❌ شما هنوز به کانال نپیوسته‌اید.',
        'join_first_then_click': 'لطفاً ابتدا به کانال بپیوندید و سپس دکمه "من پیوستم" را کلیک کنید.',
        'need_join': '❌ برای استفاده از این ربات باید ابتدا به کانال بپیوندید.',
        'invalid_link': 'لطفاً یک لینک معتبر SoundCloud ارسال کنید.',
        'link_example': 'مثال: https://soundcloud.com/artist/track-name',
        'downloading': '⏳ در حال دانلود آهنگ... لطفاً صبر کنید.',
        'download_failed': '❌ دانلود آهنگ ناموفق بود.',
        'link_check': 'لطفاً مطمئن شوید که لینک معتبر است و آهنگ به صورت عمومی در دسترس است.',
        'success': '✅ آهنگ با موفقیت دانلود و ارسال شد!',
        'send_failed': '❌ ارسال فایل صوتی ناموفق بود.',
        'downloaded_not_sent': 'فایل دانلود شد اما نتوانست ارسال شود. لطفاً دوباره تلاش کنید.',
        'error_occurred': '❌ خطایی در پردازش درخواست شما رخ داد.',
        'try_again': 'لطفاً بعداً دوباره تلاش کنید یا بررسی کنید که لینک معتبر است.',
    }
}


def get_user_language(user_id: int) -> str:
    """Get user's language preference, default to English."""
    return user_languages.get(user_id, 'en')


def t(key: str, user_id: int, **kwargs) -> str:
    """Get translated text for user."""
    lang = get_user_language(user_id)
    text = TRANSLATIONS[lang].get(key, TRANSLATIONS['en'].get(key, key))
    return text.format(**kwargs) if kwargs else text


async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is a member of the required channel."""
    try:
        user_id = update.effective_user.id
        # CHANNEL is already formatted correctly (numeric ID or @username)
        chat_member = await context.bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        
        # Print the full response dictionary for debugging
        print(f"ChatMember response: {chat_member}")
        print(f"ChatMember status: {chat_member.status}")
        print(f"ChatMember attributes: {dir(chat_member)}")
        
        # Check all possible valid statuses: creator (owner), administrator, member
        # Also check restricted (if they can still access)
        valid_statuses = ['creator', 'administrator', 'member']
        
        # If status is 'restricted', check if they can still access the chat
        if chat_member.status == 'restricted':
            # Check if restricted user can still access
            if hasattr(chat_member, 'can_send_messages') and chat_member.can_send_messages:
                return True
        
        # Check if status is in valid statuses
        is_member = chat_member.status in valid_statuses
        print(f"User membership check result: {is_member} (status: {chat_member.status})")
        
        return is_member
        
    except Exception as e:
        error_msg = str(e)
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception details: {e}")
        
        # If it's a "Member list is inaccessible" error, try alternative method
        if "Member list is inaccessible" in error_msg or "member list is inaccessible" in error_msg.lower():
            print(f"Warning: Member list is inaccessible for channel '{CHANNEL}'")
            print("This usually means:")
            print("1. Bot is not an admin of the channel")
            print("2. Channel settings don't allow membership checks")
            print("3. Trying alternative method...")
            
            # Try to check if bot itself is in the channel
            try:
                bot_info = await context.bot.get_me()
                bot_member = await context.bot.get_chat_member(chat_id=CHANNEL, user_id=bot_info.id)
                print(f"Bot's status in channel: {bot_member.status}")
                
                # If bot is admin/creator, we can't check members, so allow access
                # This is a fallback - not ideal but better than blocking everyone
                if bot_member.status in ['creator', 'administrator']:
                    print("Bot is admin but can't check members - allowing access (fallback mode)")
                    return True
            except Exception as bot_check_error:
                print(f"Could not check bot's status: {bot_check_error}")
            
            return False
            
        # If it's a "Chat not found" error, provide helpful information
        elif "Chat not found" in error_msg or "chat not found" in error_msg.lower():
            print(f"Error: Channel '{CHANNEL}' not found.")
            print("Possible reasons:")
            print("1. Channel username is incorrect")
            print("2. Bot is not an admin of the channel (required for membership checks)")
            print("3. Channel is private and bot doesn't have access")
        else:
            print(f"Error checking channel membership: {e}")
        
        print(f"Channel identifier used: {CHANNEL}")
        return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    user_id = user.id
    
    # Always check language first, regardless of membership status
    if user_id not in user_languages:
        # Show language selection
        keyboard = [
            [InlineKeyboardButton("English 🇺🇸", callback_data="lang_en")],
            [InlineKeyboardButton("فارسی 🇮🇷", callback_data="lang_fa")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Please select your language / لطفا زبان خود را انتخاب کنید",
            reply_markup=reply_markup
        )
        return
    
    # User has selected language, now check membership
    is_member = await check_channel_membership(update, context)
    
    if is_member:
        # User is already a member - skip join channel message
        await update.message.reply_text(
            f"{t('hello', user_id, name=user.first_name)}\n\n"
            f"{t('already_member', user_id)}\n\n"
            f"{t('send_link', user_id)}"
        )
    else:
        # User is not a member - show join channel message
        keyboard = []
        if CHANNEL_USERNAME:
            # CHANNEL_USERNAME is already normalized (no @ prefix)
            channel_url = f"https://t.me/{CHANNEL_USERNAME}"
            keyboard.append([InlineKeyboardButton(t('join_channel', user_id), url=channel_url)])
        keyboard.append([InlineKeyboardButton(t('i_joined', user_id), callback_data="check_membership")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"{t('hello', user_id, name=user.first_name)}\n\n"
            f"{t('join_channel_first', user_id)}\n\n"
            f"{t('join_and_click', user_id)}",
            reply_markup=reply_markup
        )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection callback."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    lang_code = query.data.split('_')[1]  # lang_en or lang_fa
    
    # Store user language preference
    user_languages[user_id] = lang_code
    
    # Check if user is already a member - if yes, skip join channel part
    is_member = await check_channel_membership(update, context)
    
    if is_member:
        # User is already a member - skip join channel message
        await query.edit_message_text(
            f"{t('hello', user_id, name=query.from_user.first_name)}\n\n"
            f"{t('already_member', user_id)}\n\n"
            f"{t('send_link', user_id)}"
        )
    else:
        # User is not a member - show join channel message
        keyboard = []
        if CHANNEL_USERNAME:
            channel_url = f"https://t.me/{CHANNEL_USERNAME}"
            keyboard.append([InlineKeyboardButton(t('join_channel', user_id), url=channel_url)])
        keyboard.append([InlineKeyboardButton(t('i_joined', user_id), callback_data="check_membership")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"{t('hello', user_id, name=query.from_user.first_name)}\n\n"
            f"{t('join_channel_first', user_id)}\n\n"
            f"{t('join_and_click', user_id)}",
            reply_markup=reply_markup
        )


async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'I Joined' button callback."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Check membership
    is_member = await check_channel_membership(update, context)
    
    if is_member:
        await query.edit_message_text(
            f"{t('verified', user_id)}\n\n"
            f"{t('send_link', user_id)}"
        )
    else:
        # Recreate the keyboard
        keyboard = []
        if CHANNEL_USERNAME:
            # CHANNEL_USERNAME is already normalized (no @ prefix)
            channel_url = f"https://t.me/{CHANNEL_USERNAME}"
            keyboard.append([InlineKeyboardButton(t('join_channel', user_id), url=channel_url)])
        keyboard.append([InlineKeyboardButton(t('i_joined', user_id), callback_data="check_membership")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"{t('not_joined', user_id)}\n\n"
            f"{t('join_first_then_click', user_id)}",
            reply_markup=reply_markup
        )


def extract_soundcloud_link(text: str) -> str | None:
    """Extract SoundCloud link from text using regex."""
    # Pattern to match SoundCloud URLs
    pattern = r'https?://(?:www\.)?(?:soundcloud\.com|on\.soundcloud\.com)/[^\s]+'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(0)
    return None


def is_soundcloud_link(text: str) -> bool:
    """Check if the text contains a SoundCloud link."""
    return extract_soundcloud_link(text) is not None


def download_soundcloud(link: str) -> tuple[str | None, str | None]:
    """
    Download SoundCloud track and return (file_path, title).
    Returns None, None on error.
    """
    temp_dir = tempfile.gettempdir()
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extractaudio': True,
        'audioformat': 'mp3',
        'audioquality': '0',  # Best quality
        'noplaylist': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info first to get title
            info = ydl.extract_info(link, download=False)
            title = info.get('title', 'track')
            
            # Clean title for filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title[:100]  # Limit length
            if not safe_title:
                safe_title = "track"
            
            # Set output template
            output_template = os.path.join(temp_dir, f"{safe_title}.%(ext)s")
            ydl_opts['outtmpl'] = output_template
            
            # Download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_download:
                ydl_download.download([link])
            
            # Find the downloaded file
            downloaded_file = None
            # Check common audio extensions
            for ext in ['mp3', 'm4a', 'opus', 'webm', 'ogg', 'flac']:
                potential_file = os.path.join(temp_dir, f"{safe_title}.{ext}")
                if os.path.exists(potential_file):
                    downloaded_file = potential_file
                    break
            
            if not downloaded_file:
                # Try to find any file with similar name in temp dir
                try:
                    for file in os.listdir(temp_dir):
                        file_path = os.path.join(temp_dir, file)
                        if os.path.isfile(file_path) and safe_title.lower() in file.lower():
                            # Check if it's a recent file (downloaded in last minute)
                            if time.time() - os.path.getmtime(file_path) < 60:
                                downloaded_file = file_path
                                break
                except Exception:
                    pass
            
            if downloaded_file and os.path.exists(downloaded_file):
                return downloaded_file, title
            else:
                return None, None
                
    except Exception as e:
        print(f"Error downloading SoundCloud track: {e}")
        return None, None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    user_id = update.effective_user.id
    
    # Check if user has selected language
    if user_id not in user_languages:
        # Show language selection
        keyboard = [
            [InlineKeyboardButton("English 🇺🇸", callback_data="lang_en")],
            [InlineKeyboardButton("فارسی 🇮🇷", callback_data="lang_fa")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Please select your language / لطفا زبان خود را انتخاب کنید",
            reply_markup=reply_markup
        )
        return
    
    # Check if user is a member
    is_member = await check_channel_membership(update, context)
    
    if not is_member:
        # Create inline keyboard
        keyboard = []
        if CHANNEL_USERNAME:
            # CHANNEL_USERNAME is already normalized (no @ prefix)
            channel_url = f"https://t.me/{CHANNEL_USERNAME}"
            keyboard.append([InlineKeyboardButton(t('join_channel', user_id), url=channel_url)])
        keyboard.append([InlineKeyboardButton(t('i_joined', user_id), callback_data="check_membership")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"{t('need_join', user_id)}\n\n"
            f"{t('join_and_click', user_id)}",
            reply_markup=reply_markup
        )
        return
    
    # Extract SoundCloud link from message using regex
    message_text = update.message.text or ""
    soundcloud_link = extract_soundcloud_link(message_text)
    
    if not soundcloud_link:
        await update.message.reply_text(
            f"{t('invalid_link', user_id)}\n\n"
            f"{t('link_example', user_id)}"
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text(t('downloading', user_id))
    
    try:
        # Download the track using the extracted link (run in executor to avoid blocking)
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(None, download_soundcloud, soundcloud_link)
        
        if not file_path or not os.path.exists(file_path):
            await processing_msg.edit_text(
                f"{t('download_failed', user_id)}\n\n"
                f"{t('link_check', user_id)}"
            )
            return
        
        # Send the audio file and wait for confirmation from Telegram API
        try:
            with open(file_path, 'rb') as audio_file:
                # send_audio returns Message object on success, raises exception on failure
                # If this succeeds, Telegram API has confirmed the file was sent
                sent_message = await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=audio_file,
                    title=title,
                    performer="SoundCloud",
                    caption=f"🎵 {title}"
                )
            
            # Only delete file after Telegram API confirms successful send
            # If we reach here, send_audio succeeded (no exception raised)
            if sent_message:
                try:
                    os.remove(file_path)
                    print(f"File deleted successfully after Telegram confirmed send: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")
            
            # Update processing message
            await processing_msg.edit_text(t('success', user_id))
            
        except Exception as send_error:
            # If sending fails, don't delete the file - keep it for potential retry
            print(f"Error sending audio file: {send_error}")
            await processing_msg.edit_text(
                f"{t('send_failed', user_id)}\n\n"
                f"{t('downloaded_not_sent', user_id)}"
            )
            # File is kept on server for potential retry
        
    except Exception as e:
        print(f"Error processing SoundCloud link: {e}")
        await processing_msg.edit_text(
            f"{t('error_occurred', user_id)}\n\n"
            f"{t('try_again', user_id)}"
        )


def main():
    """Start the bot."""
    print("Starting Telegram SoundCloud Downloader Bot...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start the bot
    print("Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()


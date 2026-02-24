import os
import json
import tempfile
import asyncio
import time
import re
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# Load environment variables
load_dotenv()

# ── Core config ───────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in environment variables")

# Admin user ID — the special user who can broadcast and manage channels
ADMIN_USER_ID = None
_admin_raw = os.getenv("ADMIN_USER_ID", "").strip()
if _admin_raw:
    try:
        ADMIN_USER_ID = int(_admin_raw)
    except ValueError:
        print(f"Warning: ADMIN_USER_ID '{_admin_raw}' is not a valid integer, ignoring.")

# Report channel — receives new-user notifications + CSV
REPORT_CHANNEL = None
_report_raw = os.getenv("REPORT_CHANNEL_ID", "").strip().lstrip("@")
if _report_raw:
    try:
        REPORT_CHANNEL = int(_report_raw)
    except ValueError:
        REPORT_CHANNEL = f"@{_report_raw}"

# ── Sponsor channels ──────────────────────────────────────────────────────────
CHANNELS_FILE = "channels.json"


def _channels_from_env() -> list:
    """Read sponsor channels from env (SPONSOR_CHANNELS or legacy single-channel vars)."""
    raw = os.getenv("SPONSOR_CHANNELS", "").strip()
    if not raw:
        # Fallback to legacy vars
        legacy = (os.getenv("CHANNEL_ID") or os.getenv("CHANNEL_USERNAME") or "").strip()
        raw = legacy
    return [c.strip() for c in raw.split(",") if c.strip()]


def load_sponsor_channels() -> list:
    """Return current list of sponsor channels (from file, seeded from env on first run)."""
    if os.path.exists(CHANNELS_FILE):
        try:
            with open(CHANNELS_FILE, "r") as f:
                return json.load(f).get("channels", [])
        except Exception:
            pass
    # First run — seed from env and persist
    channels = _channels_from_env()
    save_sponsor_channels(channels)
    return channels


def save_sponsor_channels(channels: list):
    """Persist sponsor channels to file."""
    with open(CHANNELS_FILE, "w") as f:
        json.dump({"channels": channels}, f, indent=2)


def parse_channel(ch: str):
    """Convert a channel string to the value used in Telegram API calls."""
    ch = ch.strip().lstrip("@")
    try:
        return int(ch)
    except ValueError:
        return f"@{ch}"


def channel_join_url(ch: str):
    """Return a t.me join URL for username-based channels, None for numeric IDs."""
    ch_clean = ch.strip().lstrip("@")
    try:
        int(ch_clean)   # numeric → private channel, can't auto-generate link
        return None
    except ValueError:
        return f"https://t.me/{ch_clean}"


# ── User language preferences ─────────────────────────────────────────────────
user_languages: dict = {}

# ── CSV database ──────────────────────────────────────────────────────────────
CSV_FILE = "users.csv"


def init_db():
    """Create users.csv if missing, or migrate from old single-column schema."""
    if not os.path.exists(CSV_FILE):
        pd.DataFrame(columns=["user_id", "datetime_added"]).to_csv(CSV_FILE, index=False)
        print(f"Created {CSV_FILE}")
        return

    df = pd.read_csv(CSV_FILE)
    changed = False

    # Migrate old "users" column → "user_id"
    if "users" in df.columns and "user_id" not in df.columns:
        df.rename(columns={"users": "user_id"}, inplace=True)
        changed = True

    # Add missing "datetime_added" column
    if "datetime_added" not in df.columns:
        df["datetime_added"] = ""
        changed = True

    if changed:
        df.to_csv(CSV_FILE, index=False)
        print("Migrated users.csv to new schema (user_id + datetime_added).")


def is_user_registered(user_id: int) -> bool:
    df = pd.read_csv(CSV_FILE)
    if "user_id" not in df.columns:
        return False
    return int(user_id) in df["user_id"].values


def register_user(user_id: int) -> bool:
    """Add user to CSV. Returns True if this is a brand-new user."""
    if is_user_registered(user_id):
        return False
    df = pd.read_csv(CSV_FILE)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = pd.DataFrame({"user_id": [int(user_id)], "datetime_added": [now]})
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(CSV_FILE, index=False)
    print(f"New user registered: {user_id} at {now}")
    return True


def get_all_user_ids() -> list:
    df = pd.read_csv(CSV_FILE)
    if "user_id" not in df.columns:
        return []
    return df["user_id"].dropna().astype(int).tolist()


# ── Report channel helpers ────────────────────────────────────────────────────
async def notify_new_user(context, user_id: int, user):
    """Send new-user notification text + updated CSV to the report channel."""
    if not REPORT_CHANNEL:
        return
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        name = getattr(user, "first_name", str(user_id))
        username = getattr(user, "username", None)
        uname_str = f"@{username}" if username else "no username"
        text = (
            f"👤 New user joined!\n"
            f"ID: <code>{user_id}</code>\n"
            f"Name: {name}\n"
            f"Username: {uname_str}\n"
            f"Time: {now}"
        )
        await context.bot.send_message(
            chat_id=REPORT_CHANNEL,
            text=text,
            parse_mode="HTML"
        )
        with open(CSV_FILE, "rb") as f:
            df = pd.read_csv(CSV_FILE)
            total = len(df)
            await context.bot.send_document(
                chat_id=REPORT_CHANNEL,
                document=f,
                filename="users.csv",
                caption=f"📊 Updated users list — {total} total users ({now})"
            )
    except Exception as e:
        print(f"Failed to notify report channel: {e}")


# ── Translations ──────────────────────────────────────────────────────────────
TRANSLATIONS = {
    'en': {
        'select_language': 'Please select your language / لطفا زبان خود را انتخاب کنید',
        'hello': 'Hello {name}! 👋',
        'already_member': "You're already a member of all channels! 🎉",
        'send_link': 'Send me a SoundCloud link to download the track.',
        'join_channel_first': 'To use this bot, you need to join our channel(s) first.',
        'join_and_click': "Please join the channel(s) below and then click 'I Joined'.",
        'join_channel': 'Join {name}',
        'i_joined': '✅ I Joined',
        'verified': "Great! ✅ You're verified! You can now use the bot.",
        'not_joined': "❌ You haven't joined all required channels yet.",
        'join_first_then_click': "Please join all the channels first and then click 'I Joined'.",
        'need_join': "❌ You need to join the required channel(s) to use this bot.",
        'invalid_link': 'Please send me a valid SoundCloud link.',
        'link_example': 'Example: https://soundcloud.com/artist/track-name',
        'downloading': '⏳ Downloading track... Please wait.',
        'download_failed': "❌ Failed to download the track.",
        'link_check': 'Please make sure the link is valid and the track is publicly available.',
        'success': '✅ Track downloaded and sent successfully!',
        'send_failed': "❌ Failed to send the audio file.",
        'downloaded_not_sent': "The file was downloaded but couldn't be sent. Please try again.",
        'error_occurred': "❌ An error occurred while processing your request.",
        'try_again': 'Please try again later or check if the link is valid.',
    },
    'fa': {
        'select_language': 'لطفا زبان خود را انتخاب کنید / Please select your language',
        'hello': 'سلام {name}! 👋',
        'already_member': 'شما قبلاً عضو همه کانال‌ها هستید! 🎉',
        'send_link': 'لینک SoundCloud را برای دانلود آهنگ ارسال کنید.',
        'join_channel_first': 'برای استفاده از این ربات، ابتدا باید به کانال‌های ما بپیوندید.',
        'join_and_click': 'لطفاً به کانال‌های زیر بپیوندید و سپس دکمه "من پیوستم" را کلیک کنید.',
        'join_channel': 'عضویت در {name}',
        'i_joined': '✅ من پیوستم',
        'verified': 'عالی! ✅ شما تأیید شدید! اکنون می‌توانید از ربات استفاده کنید.',
        'not_joined': '❌ هنوز به همه کانال‌های مورد نیاز نپیوسته‌اید.',
        'join_first_then_click': 'لطفاً ابتدا به همه کانال‌ها بپیوندید و سپس دکمه "من پیوستم" را کلیک کنید.',
        'need_join': '❌ برای استفاده از این ربات باید ابتدا به کانال‌ها بپیوندید.',
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
    return user_languages.get(user_id, 'en')


def t(key: str, user_id: int, **kwargs) -> str:
    lang = get_user_language(user_id)
    text = TRANSLATIONS[lang].get(key, TRANSLATIONS['en'].get(key, key))
    return text.format(**kwargs) if kwargs else text


# ── Membership helpers ────────────────────────────────────────────────────────
async def get_unjoined_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list:
    """Return list of sponsor channels the user has NOT joined."""
    user_id = update.effective_user.id
    channels = load_sponsor_channels()
    unjoined = []
    for ch in channels:
        try:
            member = await context.bot.get_chat_member(
                chat_id=parse_channel(ch), user_id=user_id
            )
            valid_statuses = ['creator', 'administrator', 'member']
            is_in = member.status in valid_statuses
            if member.status == 'restricted':
                is_in = getattr(member, 'can_send_messages', False)
            if not is_in:
                unjoined.append(ch)
        except Exception as e:
            err = str(e)
            if "Member list is inaccessible" in err:
                # Fallback: check bot's own status
                try:
                    bot_info = await context.bot.get_me()
                    bot_member = await context.bot.get_chat_member(
                        chat_id=parse_channel(ch), user_id=bot_info.id
                    )
                    if bot_member.status not in ['creator', 'administrator']:
                        unjoined.append(ch)
                except Exception:
                    pass
            else:
                print(f"Error checking channel {ch} for user {user_id}: {e}")
                # Don't block user on unexpected API errors
    return unjoined


def build_join_keyboard(unjoined: list, user_id: int) -> InlineKeyboardMarkup:
    """Build inline keyboard with a join button per unjoined channel + I Joined button."""
    keyboard = []
    for ch in unjoined:
        url = channel_join_url(ch)
        if url:
            display = ch.strip().lstrip("@")
            keyboard.append([
                InlineKeyboardButton(
                    t('join_channel', user_id, name=f"@{display}"),
                    url=url
                )
            ])
    keyboard.append([InlineKeyboardButton(t('i_joined', user_id), callback_data="check_membership")])
    return InlineKeyboardMarkup(keyboard)


# ── Admin helpers ─────────────────────────────────────────────────────────────
def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID is not None and user_id == ADMIN_USER_ID


# ── Command handlers ──────────────────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    user_id = user.id

    is_new = register_user(user_id)
    if is_new:
        await notify_new_user(context, user_id, user)

    # Language selection first
    if user_id not in user_languages:
        keyboard = [
            [InlineKeyboardButton("English 🇺🇸", callback_data="lang_en")],
            [InlineKeyboardButton("فارسی 🇮🇷", callback_data="lang_fa")]
        ]
        await update.message.reply_text(
            "Please select your language / لطفا زبان خود را انتخاب کنید",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    unjoined = await get_unjoined_channels(update, context)
    if not unjoined:
        await update.message.reply_text(
            f"{t('hello', user_id, name=user.first_name)}\n\n"
            f"{t('already_member', user_id)}\n\n"
            f"{t('send_link', user_id)}"
        )
    else:
        await update.message.reply_text(
            f"{t('hello', user_id, name=user.first_name)}\n\n"
            f"{t('join_channel_first', user_id)}\n\n"
            f"{t('join_and_click', user_id)}",
            reply_markup=build_join_keyboard(unjoined, user_id)
        )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection callback."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    register_user(user_id)

    lang_code = query.data.split('_')[1]  # lang_en or lang_fa
    user_languages[user_id] = lang_code

    unjoined = await get_unjoined_channels(update, context)
    if not unjoined:
        await query.edit_message_text(
            f"{t('hello', user_id, name=query.from_user.first_name)}\n\n"
            f"{t('already_member', user_id)}\n\n"
            f"{t('send_link', user_id)}"
        )
    else:
        await query.edit_message_text(
            f"{t('hello', user_id, name=query.from_user.first_name)}\n\n"
            f"{t('join_channel_first', user_id)}\n\n"
            f"{t('join_and_click', user_id)}",
            reply_markup=build_join_keyboard(unjoined, user_id)
        )


async def check_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'I Joined' button callback."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    register_user(user_id)

    unjoined = await get_unjoined_channels(update, context)
    if not unjoined:
        await query.edit_message_text(
            f"{t('verified', user_id)}\n\n"
            f"{t('send_link', user_id)}"
        )
    else:
        await query.edit_message_text(
            f"{t('not_joined', user_id)}\n\n"
            f"{t('join_first_then_click', user_id)}",
            reply_markup=build_join_keyboard(unjoined, user_id)
        )


# ── Admin commands ────────────────────────────────────────────────────────────
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/broadcast <message> — send message to all users (admin only)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    message_text = " ".join(context.args)
    user_ids = get_all_user_ids()
    sent, failed = 0, 0

    status_msg = await update.message.reply_text(f"⏳ Broadcasting to {len(user_ids)} users...")
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            sent += 1
        except Exception as e:
            print(f"Broadcast failed for {uid}: {e}")
            failed += 1
        await asyncio.sleep(0.05)  # avoid hitting flood limits

    await status_msg.edit_text(
        f"✅ Broadcast complete!\n"
        f"✓ Sent: {sent}\n"
        f"✗ Failed: {failed}"
    )


async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add_channel <@username or -100id> — add a sponsor channel (admin only)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /add_channel <@username or -100xxxxxxx>")
        return

    ch = context.args[0].strip()
    channels = load_sponsor_channels()
    ch_norm = ch.lstrip("@")
    if ch_norm in [c.lstrip("@") for c in channels]:
        await update.message.reply_text(f"Channel {ch} is already in the sponsor list.")
        return

    channels.append(ch)
    save_sponsor_channels(channels)
    channels_display = "\n".join(f"• {c}" for c in channels)
    await update.message.reply_text(
        f"✅ Added {ch} to sponsor channels.\n\n"
        f"📋 Current sponsor channels:\n{channels_display}"
    )


async def remove_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/remove_channel <@username or -100id> — remove a sponsor channel (admin only)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /remove_channel <@username or -100xxxxxxx>")
        return

    ch = context.args[0].strip().lstrip("@")
    channels = load_sponsor_channels()
    new_channels = [c for c in channels if c.lstrip("@") != ch]

    if len(new_channels) == len(channels):
        await update.message.reply_text(f"Channel @{ch} was not found in the sponsor list.")
        return

    save_sponsor_channels(new_channels)
    channels_display = "\n".join(f"• {c}" for c in new_channels) if new_channels else "(empty)"
    await update.message.reply_text(
        f"✅ Removed @{ch} from sponsor channels.\n\n"
        f"📋 Current sponsor channels:\n{channels_display}"
    )


async def list_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/list_channels — show all current sponsor channels (admin only)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    channels = load_sponsor_channels()
    if channels:
        channels_display = "\n".join(f"• {c}" for c in channels)
        await update.message.reply_text(f"📋 Sponsor channels ({len(channels)}):\n{channels_display}")
    else:
        await update.message.reply_text("No sponsor channels configured.")


async def send_csv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/send_csv — get the current users CSV file (admin only)."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    df = pd.read_csv(CSV_FILE)
    total = len(df)
    with open(CSV_FILE, "rb") as f:
        await context.bot.send_document(
            chat_id=user_id,
            document=f,
            filename="users.csv",
            caption=f"📊 Users database — {total} total users."
        )


# ── SoundCloud helpers ────────────────────────────────────────────────────────
def extract_soundcloud_link(text: str):
    pattern = r'https?://(?:www\.)?(?:soundcloud\.com|on\.soundcloud\.com)/[^\s]+'
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(0) if match else None


def download_soundcloud(link: str):
    """Download SoundCloud track; returns (file_path, title) or (None, None)."""
    temp_dir = tempfile.gettempdir()
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extractaudio': True,
        'audioformat': 'mp3',
        'audioquality': '0',
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            title = info.get('title', 'track')
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title[:100] or "track"
            output_template = os.path.join(temp_dir, f"{safe_title}.%(ext)s")
            ydl_opts['outtmpl'] = output_template
            with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
                ydl2.download([link])
            for ext in ['mp3', 'm4a', 'opus', 'webm', 'ogg', 'flac']:
                fp = os.path.join(temp_dir, f"{safe_title}.{ext}")
                if os.path.exists(fp):
                    return fp, title
            # Fallback: scan temp dir for recently created file matching title
            for file in os.listdir(temp_dir):
                fp = os.path.join(temp_dir, file)
                if os.path.isfile(fp) and safe_title.lower() in file.lower():
                    if time.time() - os.path.getmtime(fp) < 60:
                        return fp, title
    except Exception as e:
        print(f"Error downloading SoundCloud track: {e}")
    return None, None


# ── Message handler ───────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    user = update.effective_user
    user_id = user.id

    is_new = register_user(user_id)
    if is_new:
        await notify_new_user(context, user_id, user)

    if user_id not in user_languages:
        keyboard = [
            [InlineKeyboardButton("English 🇺🇸", callback_data="lang_en")],
            [InlineKeyboardButton("فارسی 🇮🇷", callback_data="lang_fa")]
        ]
        await update.message.reply_text(
            "Please select your language / لطفا زبان خود را انتخاب کنید",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    unjoined = await get_unjoined_channels(update, context)
    if unjoined:
        await update.message.reply_text(
            f"{t('need_join', user_id)}\n\n{t('join_and_click', user_id)}",
            reply_markup=build_join_keyboard(unjoined, user_id)
        )
        return

    message_text = update.message.text or ""
    soundcloud_link = extract_soundcloud_link(message_text)

    if not soundcloud_link:
        await update.message.reply_text(
            f"{t('invalid_link', user_id)}\n\n{t('link_example', user_id)}"
        )
        return

    processing_msg = await update.message.reply_text(t('downloading', user_id))

    try:
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(None, download_soundcloud, soundcloud_link)

        if not file_path or not os.path.exists(file_path):
            await processing_msg.edit_text(
                f"{t('download_failed', user_id)}\n\n{t('link_check', user_id)}"
            )
            return

        try:
            with open(file_path, 'rb') as audio_file:
                sent_message = await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=audio_file,
                    title=title,
                    performer="SoundCloud",
                    caption=f"🎵 {title}"
                )
            if sent_message:
                try:
                    os.remove(file_path)
                    print(f"Deleted temp file: {file_path}")
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")
            await processing_msg.edit_text(t('success', user_id))
        except Exception as send_error:
            print(f"Error sending audio file: {send_error}")
            await processing_msg.edit_text(
                f"{t('send_failed', user_id)}\n\n{t('downloaded_not_sent', user_id)}"
            )
    except Exception as e:
        print(f"Error processing SoundCloud link: {e}")
        await processing_msg.edit_text(
            f"{t('error_occurred', user_id)}\n\n{t('try_again', user_id)}"
        )


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Starting Telegram SoundCloud Downloader Bot...")

    init_db()
    channels = load_sponsor_channels()
    print(f"Sponsor channels ({len(channels)}): {channels}")
    if ADMIN_USER_ID:
        print(f"Admin user ID: {ADMIN_USER_ID}")
    if REPORT_CHANNEL:
        print(f"Report channel: {REPORT_CHANNEL}")

    app = Application.builder().token(BOT_TOKEN).build()

    # Core handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(language_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(check_membership_callback, pattern="^check_membership$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Admin handlers
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("add_channel", add_channel_command))
    app.add_handler(CommandHandler("remove_channel", remove_channel_command))
    app.add_handler(CommandHandler("list_channels", list_channels_command))
    app.add_handler(CommandHandler("send_csv", send_csv_command))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

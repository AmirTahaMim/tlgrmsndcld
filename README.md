# Telegram SoundCloud Downloader Bot

A minimal Telegram bot that allows users to download SoundCloud tracks after verifying they've joined a specific channel.

## Features

- 🌍 Multi-language support (English/Persian) with language selection
- 🔐 Channel membership verification with "I Joined" button
- 🎵 SoundCloud track downloading in best quality
- 🔍 Smart link extraction using regex (extracts links from any message)
- 📤 Automatic file sending and cleanup
- ⚡ Fast and efficient processing
- 🗃️ Automatic user tracking — every new user is saved to a local CSV database

## Prerequisites

- Python 3.8 or higher
- A Telegram bot token (get it from [@BotFather](https://t.me/BotFather))
- A Telegram channel (public or private) for membership verification
- The bot must be added as an administrator to the channel (for membership checks)

## Installation

1. **Clone or download this repository**

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   
   Create a `.env` file in the project root:
   ```env
   BOT_TOKEN=your_bot_token_here
   CHANNEL_USERNAME=tTux_tech
   CHANNEL_ID=tTux_tech
   ```
   
   **Note:** 
   - You can use either `CHANNEL_USERNAME` or `CHANNEL_ID` (or both)
   - For usernames, don't include the `@` symbol (the bot adds it automatically)
   - For private channels, use numeric `CHANNEL_ID` (e.g., `-1001234567890`)
   - If `CHANNEL_ID` is a string (username format), it will be treated as `CHANNEL_USERNAME`

## Configuration

### Getting a Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the bot token you receive

### Setting Up Channel Verification

1. Create a Telegram channel (or use an existing one)
2. Add your bot as an administrator to the channel
3. For public channels: Use the channel username (e.g., `@mychannel`)
4. For private channels: Use the channel ID (e.g., `-1001234567890`)
   - You can get the channel ID by forwarding a message from the channel to [@userinfobot](https://t.me/userinfobot)

## Usage

1. **Start the bot:**
   ```bash
   python bot.py
   ```

2. **In Telegram:**
   - Find your bot and send `/start`
   - **Select your language** (English or Persian)
   - If not a member: Join the required channel and click "I Joined" button
   - If already a member: Send a SoundCloud link to download the track
   - The bot will extract the link from your message using regex

## How It Works

1. User sends `/start` command or any message
2. **Bot asks for language selection first** (English or Persian)
3. User selects their preferred language
4. Bot checks if user is a member of the required channel
5. If not a member, bot shows channel link with "I Joined" button
6. User joins channel and clicks "I Joined"
7. Bot verifies membership
8. User sends a message containing a SoundCloud link
9. Bot extracts the link from the message using regex
10. Bot downloads the track in best quality (MP3 format)
11. Bot sends the audio file to the user
12. Bot deletes the file from the server after Telegram confirms successful send

## Supported SoundCloud Links

The bot uses regex to extract SoundCloud links from messages, so you can send:
- `https://soundcloud.com/artist/track-name`
- `https://on.soundcloud.com/...`
- Any message containing a SoundCloud URL (the bot will extract it automatically)
- Links can be anywhere in your message text

## Troubleshooting

### Bot can't verify channel membership

- Make sure the bot is added as an administrator to the channel
- For private channels, use `CHANNEL_ID` instead of `CHANNEL_USERNAME`
- Ensure the channel username doesn't include the `@` symbol in the `.env` file (the bot adds it automatically)

### Download fails

- Check if the SoundCloud link is valid and publicly accessible
- Some tracks may be restricted or unavailable
- Ensure you have a stable internet connection

### File not found errors

- The bot automatically cleans up files after sending
- If errors occur, check file permissions in the temp directory

## Requirements

See `requirements.txt` for the complete list of dependencies:

- `python-telegram-bot==20.7` - Telegram bot framework
- `yt-dlp>=2024.3.10` - SoundCloud downloader (supports best quality audio)
- `python-dotenv==1.0.0` - Environment variable management
- `pandas>=2.0.0` - User ID storage and CSV database management

## License

This project is provided as-is for educational purposes.

## Notes

- **Language Selection**: Users must select their language (English/Persian) before using the bot
- **Link Extraction**: The bot uses regex to automatically extract SoundCloud links from messages
- **File Format**: Downloads tracks in MP3 format at the best available quality
- **File Storage**: Files are temporarily stored in the system temp directory
- **File Cleanup**: Files are automatically deleted after Telegram API confirms successful send
- **Channel Access**: The bot requires administrator privileges in the channel to verify membership
- **Error Handling**: If member list is inaccessible, the bot will show helpful error messages
- **User Database**: On first run, the bot creates `users.csv` in the project directory with a `users` column. Every new user's Telegram ID is appended automatically on their first interaction.


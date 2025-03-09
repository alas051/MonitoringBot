#!/bin/bash

SCRIPT_DIR=$(dirname "$(realpath "$0")")
#BOT_URL="http://77.83.203.147/monitoringBot.py"
BOT_FILE="$SCRIPT_DIR/monitoringBot.py"

echo "📦 Installing required Python packages..."
pip install --upgrade python-telegram-bot psutil matplotlib speedtest-cli pandas

#echo "📥 Downloading the monitoring bot script..."
#curl -o "$BOT_FILE" "$BOT_URL"

#if [ $? -ne 0 ]; then
#     echo "❌ Failed to download the monitoring bot script. Exiting."
#     exit 1
# fi

#echo "✅ Download successful."

read -p "Enter your Telegram BOT TOKEN: " TOKEN
read -p "Enter your Telegram ADMIN USER ID: " ADMIN_USER_ID
read -p "Enter your server IP address: " SERVER_IP

if [[ ! $SERVER_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ Invalid IP format. Please enter a valid IP address."
    exit 1
fi

echo "⚙️ Updating the script with the provided TOKEN, ADMIN_USER_ID, and SERVER_IP..."
sed -i "s|TOKEN = \".*\"|TOKEN = \"$TOKEN\"|" "$BOT_FILE"
sed -i "s|ADMIN_USER_ID = [0-9]*|ADMIN_USER_ID = $ADMIN_USER_ID|" "$BOT_FILE"
sed -i "s|77\.83\.203\.147|$SERVER_IP|g" "$BOT_FILE"

if [ $? -ne 0 ]; then
    echo "❌ Failed to update the script. Exiting."
    exit 1
fi

echo "✅ Script updated successfully."

REPORT_DIR="$SCRIPT_DIR/reports"
mkdir -p "$REPORT_DIR" 

sed -i "s|report_dir = \"/root/alertBot/project\"|report_dir = \"$REPORT_DIR\"|" "$BOT_FILE"

if [ ! -d "$REPORT_DIR" ]; then
    echo "❌ The specified report directory does not exist. Creating it now..."
    mkdir -p "$REPORT_DIR"
    echo "✅ Directory created: $REPORT_DIR"
else
    echo "✅ Report directory exists: $REPORT_DIR"
fi

if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 is not installed. Please install Python3 to proceed."
    exit 1
fi

echo "🚀 Running the monitoring bot script..."
python3 "$BOT_FILE"

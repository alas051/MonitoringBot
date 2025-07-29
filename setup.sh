#!/bin/bash

# Step 1: Clone the repo and move into it
if [ ! -d "MonitoringBot" ]; then
    echo "📥 Cloning the MonitoringBot repository..."
    git clone https://github.com/alas051/MonitoringBot.git
    if [ $? -ne 0 ]; then
        echo "❌ Failed to clone the repository. Please check your internet connection or the repo URL."
        exit 1
    fi
else
    echo "📁 'MonitoringBot' directory already exists. Skipping clone."
fi

cd MonitoringBot || { echo "❌ Failed to enter MonitoringBot directory."; exit 1; }

SCRIPT_DIR=$(dirname "$(realpath "$0")")
BOT_FILE="$SCRIPT_DIR/bot.py"

# Function to check and install pip
check_and_install_pip() {
    if ! command -v pip &>/dev/null && ! command -v pip3 &>/dev/null; then
        echo "❌ pip is not installed. Installing python3-pip..."
        if command -v apt-get &>/dev/null; then
            sudo apt-get update
            sudo apt-get install -y python3-pip
            if [ $? -ne 0 ]; then
                echo "❌ Failed to install python3-pip. Please install it manually and try again."
                exit 1
            fi
            echo "✅ python3-pip installed successfully."
        else
            echo "❌ apt-get not found. Please install python3-pip manually for your package manager."
            exit 1
        fi
    else
        echo "✅ pip is installed."
    fi
}

echo "🔍 Checking for pip..."
check_and_install_pip

echo "📦 Installing Python packages..."
pip3 install --upgrade python-telegram-bot psutil matplotlib speedtest-cli pandas
if [ $? -ne 0 ]; then
    echo "❌ Failed to install Python packages. Please check your internet connection or pip configuration."
    exit 1
fi

read -p "Enter your Telegram BOT TOKEN: " TOKEN
read -p "Enter your Telegram ADMIN USER_ID: " ADMIN_USER_ID
read -p "Enter your server IP address: " SERVER_IP

if [[ ! $SERVER_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ Invalid IP format. Please enter a valid IP address."
    exit 1
fi

echo "⚙️ Updating the script with provided TOKEN, ADMIN_USER_ID, and SERVER_IP..."
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
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create directory: $REPORT_DIR"
        exit 1
    fi
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

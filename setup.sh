#!/bin/bash

# Define the URL to download the monitoring bot script
BOT_URL="http://80.244.11.136/monitoringBot.py"
BOT_FILE="monitoringBot.py"

pip install python-telegram-bot --upgrade
pip install psutil matplotlib speedtest-cli

# Download the Python script
echo "Downloading the monitoring bot script..."
curl -o $BOT_FILE $BOT_URL

# Check if the file was downloaded successfully
if [ $? -ne 0 ]; then
    echo "Failed to download the monitoring bot script. Exiting."
    exit 1
fi

echo "Download successful."

# Prompt the user for TOKEN and ADMIN_USER_ID
read -p "Enter your Telegram BOT TOKEN: " TOKEN
read -p "Enter your Telegram ADMIN USER ID: " ADMIN_USER_ID

# Replace placeholders for TOKEN and ADMIN_USER_ID in the Python script
echo "Updating the script with the provided TOKEN and ADMIN_USER_ID..."
sed -i "s/TOKEN = \".*\"/TOKEN = \"$TOKEN\"/" $BOT_FILE
sed -i "s/ADMIN_USER_ID = [0-9]*/ADMIN_USER_ID = $ADMIN_USER_ID/" $BOT_FILE

# Check if the replacements were successful
if [ $? -ne 0 ]; then
    echo "Failed to update the script. Exiting."
    exit 1
fi

echo "Script updated successfully."

# Make sure Python is installed and run the script
if ! command -v python3 &>/dev/null; then
    echo "Python3 is not installed. Please install Python3 to proceed."
    exit 1
fi

echo "Running the monitoring bot script..."
python3 $BOT_FILE

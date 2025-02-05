#!/bin/bash

# دریافت مسیر دایرکتوری جاری که اسکریپت در آن قرار دارد
SCRIPT_DIR=$(dirname "$(realpath "$0")")
BOT_URL="http://80.244.11.136/monitoringBot.py"
BOT_FILE="$SCRIPT_DIR/monitoringBot.py"

# نصب وابستگی‌های موردنیاز
echo "📦 Installing required Python packages..."
pip install --upgrade python-telegram-bot psutil matplotlib speedtest-cli pandas

# دانلود اسکریپت ربات
echo "📥 Downloading the monitoring bot script..."
curl -o "$BOT_FILE" "$BOT_URL"

# بررسی موفقیت دانلود
if [ $? -ne 0 ]; then
    echo "❌ Failed to download the monitoring bot script. Exiting."
    exit 1
fi

echo "✅ Download successful."

# دریافت `TOKEN` و `ADMIN_USER_ID` از کاربر
read -p "Enter your Telegram BOT TOKEN: " TOKEN
read -p "Enter your Telegram ADMIN USER ID: " ADMIN_USER_ID

# بروزرسانی مقادیر `TOKEN` و `ADMIN_USER_ID` در فایل `monitoringBot.py`
echo "⚙️ Updating the script with the provided TOKEN and ADMIN_USER_ID..."
sed -i "s|TOKEN = \".*\"|TOKEN = \"$TOKEN\"|" "$BOT_FILE"
sed -i "s|ADMIN_USER_ID = [0-9]*|ADMIN_USER_ID = $ADMIN_USER_ID|" "$BOT_FILE"

# بررسی موفقیت جایگزینی
if [ $? -ne 0 ]; then
    echo "❌ Failed to update the script. Exiting."
    exit 1
fi

echo "✅ Script updated successfully."

# ایجاد مسیر برای ذخیره فایل‌های گزارش در همان دایرکتوری اسکریپت
REPORT_DIR="$SCRIPT_DIR/reports"
mkdir -p "$REPORT_DIR"  # اطمینان از ایجاد دایرکتوری گزارش

# جایگزینی مسیر `/root/alertBot/project` در اسکریپت `monitoringBot.py` با مسیر جدید
sed -i "s|report_dir = \"/root/alertBot/project\"|report_dir = \"$REPORT_DIR\"|" "$BOT_FILE"

# بررسی و ایجاد دایرکتوری گزارش اگر وجود نداشته باشد
if [ ! -d "$REPORT_DIR" ]; then
    echo "❌ The specified report directory does not exist. Creating it now..."
    mkdir -p "$REPORT_DIR"
    echo "✅ Directory created: $REPORT_DIR"
else
    echo "✅ Report directory exists: $REPORT_DIR"
fi

# بررسی وجود Python3 و اجرای اسکریپت
if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 is not installed. Please install Python3 to proceed."
    exit 1
fi

echo "🚀 Running the monitoring bot script..."
python3 "$BOT_FILE"

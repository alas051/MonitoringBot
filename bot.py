import psutil
import matplotlib.pyplot as plt
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
import io
import asyncio
from collections import deque
import subprocess
from collections import defaultdict
import re
import ipaddress
import threading
import shlex
import pandas as pd

TOKEN = "1897499322:AAEtaPmSmDR4f7OqrccAWwRv41KMClg9LHs"

# Set your admin user ID here
ADMIN_USER_ID = 379836911  # Replace with the Telegram user ID of the admin

DEFAULT_FILE_PATH = "/var/www/html/" # for file management option

# Set of allowed users. Can contain integers (chat IDs) and strings (usernames).
allowed_users = set()

# Buffers to store data for the last minute
cpu_data = deque(maxlen=60)  # Store up to 60 entries (1 per second)
memory_data = deque(maxlen=60)
disk_data = deque(maxlen=60)

lock = asyncio.Lock()  # Lock to ensure only one task runs at a time

services = ["nginx", "mysql"]  # Services to manage

# Thresholds for alerting (None means not set)
thresholds = {
    "cpu": None,
    "memory": None,
    "disk": None
}

# Track last alert state to avoid spamming
alert_states = {
    "cpu": False,
    "memory": False,
    "disk": False
}

def get_cpu_details():
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count(logical=True)
    return {"percent": cpu_percent, "count": cpu_count}

def get_memory_details():
    memory = psutil.virtual_memory()
    return {
        "total": memory.total // (1024 * 1024),  # Convert to MB
        "used": memory.used // (1024 * 1024),
        "percent": memory.percent,
    }

def get_disk_details():
    disk = psutil.disk_usage('/')
    return {
        "total": disk.total // (1024 * 1024),  # Convert to MB
        "used": disk.used // (1024 * 1024),
        "percent": disk.percent,
    }

def get_uptime():
    boot_time = psutil.boot_time()
    current_time = time.time()
    uptime_seconds = int(current_time - boot_time)
    days = uptime_seconds // (24 * 3600)
    hours = (uptime_seconds % (24 * 3600)) // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    return f"{days}d {hours}h {minutes}m {seconds}s"

def get_service_status(service_name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        status = result.stdout.strip()
        emoji = "✅" if status == "active" else "❌"
        return f"{emoji} {status}"
    except Exception as e:
        return f"⚠️ Error: {e}"

def manage_service(service_name, action):
    try:
        result = subprocess.run(
            ["sudo", "systemctl", action, service_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0:
            return f"Service `{service_name}` {action}ed successfully."
        else:
            return f"Failed to {action} service `{service_name}`.\nError: {result.stderr.strip()}"
    except Exception as e:
        return f"Error: {e}"

#******************Network *****************
def run_speedtest():
    """
    Runs speedtest-cli --simple and parses the output for ping, download, upload.
    Returns:
        ping (float or None)
        download (float or None) in Mbit/s
        upload (float or None) in Mbit/s
        error (str or None)
    """
    try:
        result = subprocess.run(
            ["speedtest-cli", "--simple"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            return None, None, None, result.stderr.strip()

        lines = result.stdout.split("\n")
        ping = download = upload = None

        for line in lines:
            if line.startswith("Ping:"):
                # e.g. "Ping: 16.845 ms"
                # Extract numeric part
                try:
                    ping_str = line.split(":")[1].strip().split(" ")[0]
                    ping = float(ping_str)
                except:
                    pass
            elif line.startswith("Download:"):
                # e.g. "Download: 45.67 Mbit/s"
                try:
                    download_str = line.split(":")[1].strip().split(" ")[0]
                    download = float(download_str)
                except:
                    pass
            elif line.startswith("Upload:"):
                # e.g. "Upload: 23.41 Mbit/s"
                try:
                    upload_str = line.split(":")[1].strip().split(" ")[0]
                    upload = float(upload_str)
                except:
                    pass

        return ping, download, upload, None
    except Exception as e:
        return None, None, None, str(e)

def get_packet_loss():
    """
    Uses 'ping -c 4 google.com' to measure packet loss percentage.
    Returns:
        packet_loss (float or None)
        error (str or None)
    """
    try:
        result = subprocess.run(
            ["ping", "-c", "4", "google.com"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            # Non-zero exit code can mean no network or partial packets lost
            # We'll still parse the output if possible
            # but store the stderr as error
            error_msg = result.stderr.strip()
        else:
            error_msg = None

        # Attempt to parse the stdout
        output = result.stdout
        packet_loss_line = [line for line in output.split("\n") if "packet loss" in line]
        if not packet_loss_line:
            # Could not find a line containing "packet loss"
            return None, error_msg or "Could not parse packet loss"

        # E.g. "4 packets transmitted, 4 received, 0% packet loss, time 4003ms"
        line = packet_loss_line[0]
        # Extract the substring like "0% packet loss"
        try:
            loss_part = line.split(",")[2].strip()  # e.g. "0% packet loss"
            loss_value_str = loss_part.split("%")[0].strip()
            packet_loss = float(loss_value_str)
            return packet_loss, error_msg
        except:
            return None, error_msg or "Could not parse packet loss"
    except Exception as e:
        return None, str(e)




def generate_chart(data, label):
    plt.figure(figsize=(6, 4))
    plt.plot(data, marker='o', label=label)
    plt.title(f'{label} Usage Over Last Minute')
    plt.xlabel('Time (Seconds Ago)')
    plt.ylabel('Usage (%)')
    plt.ylim(0, 100)
    plt.grid(True)
    plt.legend()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

def is_authorized_user(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False     
    # Admin always allowed
    if user.id == ADMIN_USER_ID:
        return True
    # Check if user is in allowed_users set
    if user.id in allowed_users:
        return True
    if user.username and user.username in allowed_users:
        return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized_user(update):
        await update.message.reply_text("You are not authorized to use this bot.")
        return

    welcome_message = (
    "👋 *Welcome to the Server Monitoring Bot!* 🚀\n\n"
    "I’m here to help you *monitor, manage, and secure* your Linux server effortlessly. "
    "With me, you can *track system performance, manage services, monitor network health, "
    "automate alerts, handle files, and generate reports!*\n\n"
    
    "Here’s what I can do for you:\n"
    "📊 *Monitor Server Resources*: Track **CPU, memory, disk usage, and uptime** in real-time.\n"
    "🛠 *Manage Services*: Start, stop, restart, or check the status of services like **Nginx, MySQL, and more.**\n"
    "🌐 *Network Tools*: Run **speed tests**, check **packet loss**, and monitor **network stability.**\n"
    "⚠️ *Custom Alerts*: Set up notifications for **high CPU usage, low disk space**, and other critical thresholds.\n"
    "🔐 *Security Monitoring*: Detect and block **suspicious login attempts**, monitor **DDoS attacks**, and manage **blocked IPs.**\n"
    "📄 *Daily Server Reports*: Receive detailed **CSV reports** of server performance over the last 24 hours.\n"
    "📂 *File Management*: **Upload, download, and delete** files from your server easily.\n"
    "⌨️ *Run Linux Commands*: Execute **pre-approved system commands** remotely.\n\n"

    "💻 *To run a command, start with* `/cmd`.\n"
    "Example: `/cmd uptime` or `/cmd df -h`\n\n"
    "🔎 *To view the list of available commands, use* `/cmd list`.\n\n"
    
    "📝 Use the buttons below to get started and keep your server in top shape! 💻🔧"
)




    keyboard = [
        [
            InlineKeyboardButton("📊 Monitoring", callback_data="monitoring_main"),
            InlineKeyboardButton("🛠 Manage Services", callback_data="services_main")
        ],
        [
            InlineKeyboardButton("🌐 Networking", callback_data="networking_main"),
            InlineKeyboardButton("⚠️ Alerting", callback_data="alerting_main")
        ],
        [
            InlineKeyboardButton("🔐 Security", callback_data="security_main"),  
            InlineKeyboardButton("📄 Daily Report", callback_data="request_daily_report")
        ],
        [
            InlineKeyboardButton("📂 File Management", callback_data="file_management")
        ]        

    ]

    # If admin, add "Manage Users" button in a separate row
    if update.effective_user.id == ADMIN_USER_ID:
        keyboard.append([InlineKeyboardButton("🔒 Manage Users", callback_data="manage_users_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    #await update.message.reply_text("Select a category:", reply_markup=reply_markup)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")


################# security functions ###################3

# تنظیمات امنیتی
FAILED_ATTEMPTS_THRESHOLD = 5  # حداکثر تلاش‌های ناموفق قبل از بلاک شدن
DDoS_CONNECTION_THRESHOLD = 50  # حداکثر تعداد اتصالات همزمان قبل از بلاک شدن
AUTH_LOG_PATH = "/var/log/auth.log"  # مسیر لاگ‌های احراز هویت در لینوکس

# متغیرهای ذخیره‌سازی
failed_attempts = defaultdict(int)  # ذخیره تلاش‌های ناموفق ورود به SSH
blocked_ips = set()  # ذخیره IPهای بلاک شده


### 🛠 **تابع بررسی حملات SSH Brute Force**
async def monitor_ssh_log(app: Application):
    """مانیتورینگ لاگ‌های SSH برای تشخیص حملات Brute Force"""
    print("🔍 مانیتورینگ SSH فعال شد...")

    with subprocess.Popen(["tail", "-F", AUTH_LOG_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        while True: 
            line = process.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue

            # شناسایی تلاش‌های ناموفق ورود
            match = re.search(r"Failed password for .* from (\d+\.\d+\.\d+\.\d+)", line)
            if match:
                ip = match.group(1)
                failed_attempts[ip] += 1
                if failed_attempts[ip] >= FAILED_ATTEMPTS_THRESHOLD:
                    if ip == "77.83.203.147":  # جلوگیری از بلاک شدن سرور                    
                        print(f"⚠️ IP سرور ({ip}) شناسایی شد، اما بلاک نخواهد شد.")
                    elif ip not in blocked_ips:
                        print(f"✅ Blocking {ip} ...")
                        await send_security_alert(app, ip, "SSH Brute Force Attack")
                        block_ip(ip)
                        blocked_ips.add(ip)


### 🚨 **ارسال هشدار به تلگرام**
async def send_security_alert(app: Application, ip: str, attack_type: str):
    """ارسال هشدار در صورت مشاهده حمله"""
    msg = f"🚨 **Security Alert!** 🚨\n🔴 Attack Type: `{attack_type}`\n🔍 Suspicious IP: `{ip}`\n⚠️ This IP has been blocked."
    await app.bot.send_message(chat_id=ADMIN_USER_ID, text=msg, parse_mode="Markdown")


### 🛡 **بلاک کردن IP مشکوک**
def block_ip(ip: str):
    """بستن خودکار IP مشکوک"""
    if ip == "77.83.203.147":  # جلوگیری از بلاک شدن سرور
        print(f"⚠️ Server IP ({ip}) detected, but it will not be blocked.")
        return
    subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"])
    print(f"⛔ IP {ip} has been blocked.")

### 🔓 **آنبلاک کردن IP**
def unblock_ip(ip: str):
    """باز کردن IP بلاک شده"""
    subprocess.run(["sudo", "iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"])
    print(f"✅ IP {ip} has been unblocked.")

### 📋 **دریافت لیست IPهای بلاک شده**

def get_blocked_ips():
    """دریافت لیست IPهایی که واقعاً بلاک شده‌اند"""
    result = subprocess.run(["sudo", "iptables", "-L", "INPUT", "-v", "-n"], stdout=subprocess.PIPE, text=True)
    lines = result.stdout.split("\n")
    blocked_ips = []

    for line in lines:
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)  # پیدا کردن آی‌پی در هر خط
        if match and "DROP" in line:  # بررسی اینکه خط حاوی دستور DROP باشد
            blocked_ips.append(match.group(1))

    return blocked_ips



### 🔥 **بررسی حملات DDoS**
async def check_ddos_attack(app: Application):
    """بررسی میزان اتصالات همزمان برای تشخیص حملات DDoS"""
    while True:
        await asyncio.sleep(60)  # هر 60 ثانیه بررسی شود
        result = subprocess.run(["netstat", "-tn"], stdout=subprocess.PIPE, text=True)
        ip_counts = defaultdict(int)

        for line in result.stdout.split("\n"):
            match = re.search(r"(\d+\.\d+\.\d+\.\d+):\d+", line)
            if match:
                ip = match.group(1)
                ip_counts[ip] += 1

        for ip, count in ip_counts.items():
            if count > DDoS_CONNECTION_THRESHOLD:
                if ip == "77.83.203.147":  # جلوگیری از بلاک شدن سرور
                    print(f"⚠️ Server IP ({ip}) detected, but it will not be blocked.")
                elif ip not in blocked_ips:
                    await send_security_alert(app, ip, "DDoS Attack")
                    block_ip(ip)
                    blocked_ips.add(ip)

def is_valid_ip(ip: str) -> bool:
    """بررسی صحت فرمت IP آدرس"""
    pattern = r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"
    return re.match(pattern, ip) is not None

#########################################################################################

######################################  Daily Report    ######################################
from collections import deque
import datetime

# ذخیره اطلاعات منابع سرور در ۲۴ ساعت گذشته (هر ۵ دقیقه یک بار)
resource_history = {
    "cpu": deque(maxlen=288),  # 288 رکورد برای 24 ساعت (هر 5 دقیقه یک رکورد)
    "memory": deque(maxlen=288),
    "disk": deque(maxlen=288),
    "timestamps": deque(maxlen=288)  # برای ذخیره زمان هر اندازه‌گیری
}
async def collect_daily_data():
    """ جمع‌آوری داده‌های منابع سرور هر ۵ دقیقه یک بار """
    print("📊 Collecting daily resource data...")

    while True:
        # مقداردهی مستقیم بدون نیاز به حلقه
        cpu_samples = [psutil.cpu_percent(interval=1)]
        memory_samples = [psutil.virtual_memory().percent]
        disk_samples = [psutil.disk_usage('/').percent]

        # بررسی لیست‌های خالی برای جلوگیری از تقسیم بر صفر
        avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else psutil.cpu_percent(interval=1)
        avg_memory = sum(memory_samples) / len(memory_samples) if memory_samples else psutil.virtual_memory().percent
        avg_disk = sum(disk_samples) / len(disk_samples) if disk_samples else psutil.disk_usage('/').percent
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ذخیره داده‌ها در تاریخچه
        resource_history["cpu"].append(avg_cpu)
        resource_history["memory"].append(avg_memory)
        resource_history["disk"].append(avg_disk)
        resource_history["timestamps"].append(timestamp)

        print(f"✅ Data saved: {timestamp} - CPU: {avg_cpu:.2f}%, Memory: {avg_memory:.2f}%, Disk: {avg_disk:.2f}%")

        await asyncio.sleep(300)  # هر ۵ دقیقه یک بار اجرا شود


# def record_initial_resource_data():
#     """ ثبت اولین مقدار در تاریخچه منابع سرور (اگر خالی باشد) """
#     if not resource_history["cpu"]:  # اگر خالی است، مقداردهی اولیه کن
#         print("✅ Recording initial resource data...")
#         for _ in range(5):  # ذخیره ۵ مقدار در بازه ۱۰ ثانیه‌ای
#             cpu = psutil.cpu_percent(interval=2)
#             memory = psutil.virtual_memory().percent
#             disk = psutil.disk_usage('/').percent
#             timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#             resource_history["cpu"].append(cpu)
#             resource_history["memory"].append(memory)
#             resource_history["disk"].append(disk)
#             resource_history["timestamps"].append(timestamp)
        
#         print(f"✅ Initial resource data recorded: CPU={cpu}%, Memory={memory}%, Disk={disk}%")


import os
def generate_daily_report_csv():
    """ تولید گزارش روزانه و جلوگیری از CSV خالی """

    report_dir = "/root/alertBot/project"  # مسیر دقیق ذخیره فایل
    csv_filename = "server_daily_report.csv"
    csv_path = os.path.join(report_dir, csv_filename)  # ترکیب مسیر و نام فایل

    if not resource_history["cpu"]:  # اگر داده‌ای وجود ندارد، مقداردهی اولیه انجام شود
        print("⚠️ No data found, recording initial resource data...")
        return None  # جلوگیری از ارسال فایل خالی

    # میانگین داده‌های ذخیره‌شده در تاریخچه
    avg_cpu = sum(resource_history["cpu"]) / len(resource_history["cpu"]) if resource_history["cpu"] else psutil.cpu_percent()
    avg_memory = sum(resource_history["memory"]) / len(resource_history["memory"]) if resource_history["memory"] else psutil.virtual_memory().percent
    avg_disk = sum(resource_history["disk"]) / len(resource_history["disk"]) if resource_history["disk"] else psutil.disk_usage('/').percent

    # ایجاد DataFrame برای منابع
    df_resources = pd.DataFrame({
        "Metric": ["Avg CPU Usage (%)", "Avg Memory Usage (%)", "Avg Disk Usage (%)"],
        "Value": [avg_cpu, avg_memory, avg_disk]
    })
    
    # داده‌های تاریخچه
    df_history = pd.DataFrame({
        "Timestamp": list(resource_history["timestamps"]),
        "CPU Usage (%)": list(resource_history["cpu"]),
        "Memory Usage (%)": list(resource_history["memory"]),
        "Disk Usage (%)": list(resource_history["disk"])
    })

    # ذخیره CSV
    df_resources.to_csv(csv_path, index=False)
    df_history.to_csv(csv_path, index=False, mode='a')  # Append historical data

    print(f"📄 Daily report generated successfully at {csv_path}")
    return csv_path  # مسیر کامل فایل را برمی‌گرداند


async def send_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ ارسال گزارش روزانه در قالب فایل CSV به ادمین """

    if update.effective_user.id != ADMIN_USER_ID:
        await update.callback_query.answer("⛔ You are not authorized to request this report.", show_alert=True)
        return

    await update.callback_query.answer("⏳ Generating report...", show_alert=False)

    if len(resource_history["cpu"]) < 1:  # اگر هنوز هیچ داده ۵ دقیقه‌ای ثبت نشده باشد
        cpu_now = psutil.cpu_percent(interval=1)
        mem_now = psutil.virtual_memory().percent
        disk_now = psutil.disk_usage('/').percent
        text = (
            "⚠️ **No historical data available! Sending real-time usage:**\n\n"
            f"🔹 **CPU Usage:** `{cpu_now:.2f}%`\n"
            f"🔹 **Memory Usage:** `{mem_now:.2f}%`\n"
            f"🔹 **Disk Usage:** `{disk_now:.2f}%`\n"
        )
        await update.callback_query.message.reply_text(text, parse_mode="Markdown")
        return

    # تولید گزارش CSV
    csv_path = generate_daily_report_csv()

    if not csv_path or not os.path.exists(csv_path):
        await update.callback_query.message.reply_text("⚠️ **Report file not found!**\nTry again later.", parse_mode="Markdown")
        return

    print(f"📂 Checking file path: {csv_path}")

    try:
        # ارسال فایل
        with open(csv_path, "rb") as file:
            await context.bot.send_document(chat_id=ADMIN_USER_ID, document=file, filename=os.path.basename(csv_path))

        await update.callback_query.message.reply_text("✅ **Daily report sent successfully!**", parse_mode="Markdown")

    except Exception as e:
        print(f"⚠️ Error sending file: {e}")
        await update.callback_query.message.reply_text(f"❌ **Failed to send report:** {str(e)}", parse_mode="Markdown")



######################################### File management  ###################################

async def file_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی مدیریت فایل‌ها"""
    keyboard = [
        [
            InlineKeyboardButton("📂 View Files", callback_data="list_files"),
            InlineKeyboardButton("📤 Upload File", callback_data="upload_file")
        ],
        [
            InlineKeyboardButton("🗑 Delete File", callback_data="delete_file_menu"),
            InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.message.edit_text("📁 **File Management Menu**\nChoose an option:", reply_markup=reply_markup, parse_mode="Markdown")



import os

async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش لیست فایل‌ها در مسیر `/var/www/html/`"""
    files = os.listdir(DEFAULT_FILE_PATH)
    if not files:
        await update.callback_query.message.edit_text("📂 No files found in `/var/www/html/`.")
        return

    file_buttons = [[InlineKeyboardButton(f"📄 {file}", callback_data=f"get_file_{file}")] for file in files]
    file_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="file_management")])

    reply_markup = InlineKeyboardMarkup(file_buttons)
    await update.callback_query.message.edit_text("📂 **Available Files:**\nSelect a file to download:", reply_markup=reply_markup, parse_mode="Markdown")


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال فایل انتخاب شده به تلگرام"""
    query = update.callback_query
    filename = query.data.split("get_file_")[1]
    file_path = os.path.join(DEFAULT_FILE_PATH, filename)

    if os.path.exists(file_path):
        await context.bot.send_document(chat_id=ADMIN_USER_ID, document=open(file_path, "rb"), filename=filename)
        await query.answer("📄 File sent successfully!", show_alert=True)
    else:
        await query.answer("⚠️ File not found!", show_alert=True)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ذخیره فایل ارسال شده توسط ادمین در `/var/www/html/`"""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ You are not authorized to upload files.")
        return

    if 'awaiting_file_upload' not in context.user_data or not context.user_data['awaiting_file_upload']:
        await update.message.reply_text("❌ Please use the '📤 Upload File' option first.")
        return

    file = update.message.document
    file_name = file.file_name
    file_path = os.path.join(DEFAULT_FILE_PATH, file_name)

    file_obj = await context.bot.get_file(file.file_id)  # دریافت فایل از تلگرام
    
    # دانلود فایل و ذخیره در مسیر موردنظر
    await file_obj.download_to_drive(file_path)

    context.user_data['awaiting_file_upload'] = False  # حالت دریافت فایل غیرفعال می‌شود
    await update.message.reply_text(f"✅ File `{file_name}` saved successfully in `/var/www/html/`!", parse_mode="Markdown")


async def delete_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """منوی حذف فایل"""
    files = os.listdir(DEFAULT_FILE_PATH)
    if not files:
        await update.callback_query.message.edit_text("📂 No files available to delete.")
        return

    file_buttons = [[InlineKeyboardButton(f"🗑 {file}", callback_data=f"delete_file_{file}")] for file in files]
    file_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="file_management")])

    reply_markup = InlineKeyboardMarkup(file_buttons)
    await update.callback_query.message.edit_text("🗑 **Select a file to delete:**", reply_markup=reply_markup, parse_mode="Markdown")

async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف فایل انتخاب شده"""
    query = update.callback_query
    filename = query.data.split("delete_file_")[1]
    file_path = os.path.join(DEFAULT_FILE_PATH, filename)

    if os.path.exists(file_path):
        os.remove(file_path)
        await query.answer(f"✅ File `{filename}` deleted!", show_alert=True)
        await delete_file_menu(update, context)
    else:
        await query.answer("⚠️ File not found!", show_alert=True)





########################################################################################

############################################### cmd function #################


# لیست دستورات مجاز برای اجرا
ALLOWED_COMMANDS = ["ls", "df", "uptime", "free", "tail", "ps aux", "whoami", "cat"]
async def execute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ اجرای یک دستور لینوکس و ارسال خروجی در تلگرام """

    if not is_authorized_user(update):
        await update.message.reply_text("⛔ You are not authorized to execute commands.")
        return

    if not context.args:
        await update.message.reply_text("❌ Please provide a command. Example: `/cmd uptime`", parse_mode="Markdown")
        return

    # دریافت دستور کاربر
    command = " ".join(context.args)

    # بررسی دستور list برای نمایش دستورات مجاز
    if command == "list":
        allowed_commands_str = "\n".join(ALLOWED_COMMANDS)
        await update.message.reply_text(
    f"✨ *Allowed Commands List:*\n\n"
    f"🔹 _The following commands are available to execute:_\n\n"
    f"{allowed_commands_str}\n\n"
    f"📝 To run any command, use the format: `/cmd <command>`.\n"
    f"💡 For example: `/cmd uptime`",
    parse_mode="Markdown"
)

        return

    # بررسی مجاز بودن دستور
    if command.split()[0] not in [cmd.split()[0] for cmd in ALLOWED_COMMANDS]:
        await update.message.reply_text(f"🚫 Command `{command}` is not allowed.", parse_mode="Markdown")
        return

    try:
        # استفاده از shlex برای جلوگیری از حملات shell injection
        result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        
        # بررسی خروجی و ارسال به تلگرام
        output = result.stdout.strip() if result.stdout else result.stderr.strip()
        
        if len(output) > 4000:
            # اگر خروجی خیلی طولانی باشد، آن را در یک فایل ذخیره و ارسال کنیم
            with open("command_output.txt", "w") as f:
                f.write(output)
            await update.message.reply_document(document=open("command_output.txt", "rb"))
        else:
            await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Execution took too long and was terminated.")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error executing command:\n`{str(e)}`", parse_mode="Markdown")

        
#################################################################

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized_user(update):
        await query.edit_message_text("You are not authorized to use this bot.")
        return

    if query.data == "monitoring_main":
        keyboard = [
            [
                InlineKeyboardButton("CPU", callback_data="cpu"),
                InlineKeyboardButton("Memory", callback_data="memory"),
            ],
            [
                InlineKeyboardButton("Disk", callback_data="disk"),
                InlineKeyboardButton("Uptime", callback_data="uptime"),
            ],
            [InlineKeyboardButton("🔙  Back", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select a resource to monitor:", reply_markup=reply_markup)

    elif query.data == "services_main":
        service_buttons = []
        for pair in chunk_list(services, 2):
            row = [InlineKeyboardButton(s, callback_data=f"service_{s}") for s in pair]
            service_buttons.append(row)

        service_buttons.append([
            InlineKeyboardButton("Add Service", callback_data="add_service"),
            InlineKeyboardButton("Remove Service", callback_data="remove_service")
        ])
        service_buttons.append([InlineKeyboardButton("🔙  Back", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(service_buttons)
        await query.edit_message_text("Select a service to manage:", reply_markup=reply_markup)

    elif query.data == "manage_users_main":
        # This menu should only appear for admin
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage users.")
            return

        keyboard = [
    [
        InlineKeyboardButton("➕ Add User", callback_data="add_user"),
        InlineKeyboardButton("➖ Remove User", callback_data="remove_user_menu")
    ],
    [
        InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
    ]
]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Manage Users:", reply_markup=reply_markup)


    elif query.data == "add_user":
        # Ask admin to enter username or chat ID
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage users.")
            return

        await query.edit_message_text("Please send the username or chat ID of the user you want to add.")
        context.user_data['awaiting_user_to_add'] = True

    elif query.data == "remove_user_menu":
        # Show allowed users in a menu to remove
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage users.")
            return

        if not allowed_users:
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="manage_users_main")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("No users found.", reply_markup=reply_markup)
        else:
            remove_buttons = []
            allowed_list = list(allowed_users)
            display_list = [str(u) for u in allowed_list]
            for pair in chunk_list(display_list, 2):
                row = [InlineKeyboardButton(f"Remove {p}", callback_data=f"remove_user_{p}") for p in pair]
                remove_buttons.append(row)

            remove_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="manage_users_main")])
            reply_markup = InlineKeyboardMarkup(remove_buttons)
            await query.edit_message_text("Select a user to remove:", reply_markup=reply_markup)

    elif query.data.startswith("remove_user_"):
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage users.")
            return

        user_identifier = query.data.split("remove_user_")[1]
        to_remove = int(user_identifier) if user_identifier.isdigit() else user_identifier

        if to_remove in allowed_users:
            allowed_users.remove(to_remove)
            await query.edit_message_text(f"User '{user_identifier}' removed successfully.")
        else:
            await query.edit_message_text(f"User '{user_identifier}' not found.")

###############network###############

    elif query.data == "networking_main":
        keyboard = [
        [
            InlineKeyboardButton("Speedtest", callback_data="speedtest"),
            InlineKeyboardButton("Packet Loss", callback_data="packet_loss")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="back_to_main")
        ]
    ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select a network metric to measure:", reply_markup=reply_markup)


    elif query.data == "speedtest":
        # Existing speedtest code
        ping, download, upload, err = run_speedtest()
        if err:
            text = f"Error during speedtest: `{err}`"
        else:
            text = (
                f"**Download Speed**\n\n"
                f"- Ping: `{ping if ping else 'N/A'}` ms\n"
                f"- Download: `{download if download else 'N/A'}` Mbit/s\n"
                f"- Upload: `{upload if upload else 'N/A'}` Mbit/s\n"
            )
###
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="networking_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)   
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

#        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "packet_loss":
        # NEW: handle the packet loss button
        loss, err = get_packet_loss()
        if err:
            text = f"Error measuring packet loss: `{err}`"
        else:
            text = f"**Packet Loss**: {loss}%"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="networking_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)   
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
#        await query.edit_message_text(text, parse_mode="Markdown")


#######################################################

    elif query.data == "back_to_main":
        keyboard = [
            [
                InlineKeyboardButton("📊 Monitoring", callback_data="monitoring_main"),
                InlineKeyboardButton("🛠 Manage Services", callback_data="services_main")
            ],
            [
                InlineKeyboardButton("🌐 Networking", callback_data="networking_main"),
                InlineKeyboardButton("⚠️ Alerting", callback_data="alerting_main")
            ],
            [
                InlineKeyboardButton("🔐 Security", callback_data="security_main"),  
                InlineKeyboardButton("📄 Daily Report", callback_data="request_daily_report")
            ],
            [
                InlineKeyboardButton("📂 File Management", callback_data="file_management")
            ]        

        ]

        # If admin, add "Manage Users" button in a separate row
        if query.from_user.id == ADMIN_USER_ID:
            keyboard.append([InlineKeyboardButton("🔒 Manage Users", callback_data="manage_users_main")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select a category:", reply_markup=reply_markup)

###############3 daily report ###################
    elif query.data == "request_daily_report":
        await send_daily_report(update, context)

##############  file management ###########


    elif query.data == "file_management":
        await file_management_menu(update, context)

    elif query.data == "list_files":
        await list_files(update, context)

    elif query.data.startswith("get_file_"):
        await send_file(update, context)

    elif query.data == "delete_file_menu":
        await delete_file_menu(update, context)

    elif query.data.startswith("delete_file_"):
        await delete_file(update, context)

    elif query.data == "upload_file":
        await query.message.reply_text("📤 لطفاً فایل موردنظر را ارسال کنید تا در مسیر `/var/www/html/` ذخیره شود.")
        context.user_data['awaiting_file_upload'] = True  # حالت دریافت فایل فعال می‌شود

        



##############

    elif query.data == "alerting_main":
        # Alerting is visible to all authorized users
        # However, only admin can set/remove thresholds. Non-admin users just see the current thresholds.
        if query.from_user.id == ADMIN_USER_ID:
            # 2 buttons in each row: Set + Remove for each resource, then a "Back" row
            keyboard = [
                [
                    InlineKeyboardButton("➕ CPU Threshold", callback_data="set_cpu_threshold"),
                    InlineKeyboardButton("➖ CPU Threshold", callback_data="remove_cpu_threshold")
                ],
                [
                    InlineKeyboardButton("➕ Memory Threshold", callback_data="set_memory_threshold"),
                    InlineKeyboardButton("➖ Memory Threshold", callback_data="remove_memory_threshold")
                ],
                [
                    InlineKeyboardButton("➕ Disk Threshold", callback_data="set_disk_threshold"),
                    InlineKeyboardButton("➖ Disk Threshold", callback_data="remove_disk_threshold")
                ],
                [InlineKeyboardButton("🔙  Back", callback_data="back_to_main")]
            ]
        else:
            # Non-admin users just see current thresholds and a back button
            keyboard = [[InlineKeyboardButton("🔙  Back", callback_data="back_to_main")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Current Thresholds:\nCPU: {thresholds['cpu']}%\nMemory: {thresholds['memory']}%\nDisk: {thresholds['disk']}%\n\n",
            reply_markup=reply_markup
        )

    elif query.data in ["set_cpu_threshold", "set_memory_threshold", "set_disk_threshold"]:
        # Admin sets threshold
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage alerts.")
            return

        resource = query.data.split("_")[1]
        context.user_data['awaiting_threshold_resource'] = resource
        await query.edit_message_text(f"Please send the {resource.capitalize()} threshold in percent (e.g. 80):")

    # --- NEW: Handle removing thresholds ---
    elif query.data in ["remove_cpu_threshold", "remove_memory_threshold", "remove_disk_threshold"]:
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage alerts.")
            return

        # resource name is the second item, e.g. "remove_cpu_threshold" -> split("_") -> ["remove", "cpu", "threshold"]
        resource = query.data.split("_")[1]
        thresholds[resource] = None
        alert_states[resource] = False  # Reset alert state if removing threshold
        await query.edit_message_text(f"{resource.capitalize()} threshold removed.")

  
    elif query.data == "cpu":
        current_usage = cpu_data[-1] if cpu_data else 0
        details = get_cpu_details()
        text = (
            "**CPU Usage Over Last Minute:**\n"
            f"- Total Cores: {details['count']} cores\n"
            f"- Current Usage: {current_usage:.2f}%\n"
        )

    # Generate the chart
        chart_buf = generate_chart(list(cpu_data), "CPU")

    # Send the chart image first
        await query.message.reply_photo(photo=chart_buf)

    # Then send the text and back button
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    elif query.data == "memory":
        current_usage = memory_data[-1] if memory_data else 0
        details = get_memory_details()
        text = (
            "**Memory Usage Over Last Minute:**\n"
            f"- Total: {details['total']} MB\n"
            f"- Used: {details['used']} MB ({current_usage:.2f}%)\n"
        )
        chart_buf = generate_chart(list(memory_data), "Memory")
        await query.message.reply_photo(photo=chart_buf)


        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


    elif query.data == "disk":
        current_usage = disk_data[-1] if disk_data else 0
        details = get_disk_details()
        text = (
            "**Disk Usage Over Last Minute:**\n"
            f"- Total: {details['total']} MB\n"
            f"- Used: {details['used']} MB ({current_usage:.2f}%)\n"
        )
        chart_buf = generate_chart(list(disk_data), "Disk")
        await query.message.reply_photo(photo=chart_buf)
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    elif query.data == "uptime":
        uptime = get_uptime()
        text = f"⏱ **Server Uptime:**\n- {uptime}"
        await query.edit_message_text(text, parse_mode="Markdown")
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    elif query.data == "add_service":
        await query.edit_message_text("Please send the name of the service you want to add.")
        context.user_data['awaiting_service_name'] = True

    elif query.data == "remove_service":
        remove_buttons = []
        for pair in chunk_list(services, 2):
            row = [InlineKeyboardButton(f"Remove {s}", callback_data=f"remove_{s}") for s in pair]
            remove_buttons.append(row)

        remove_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="services_main")])
        reply_markup = InlineKeyboardMarkup(remove_buttons)
        await query.edit_message_text("Select a service to remove:", reply_markup=reply_markup)

    elif query.data.startswith("remove_"):
        service_name = query.data.split("_")[1]
        if service_name in services:
            services.remove(service_name)
            text = f"Service `{service_name}` removed successfully."
        else:
            text = f"Service `{service_name}` not found."
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="services_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)

    elif query.data.startswith("service_"):
        service_name = query.data.split("_")[1]
        status = get_service_status(service_name)

        text = (
            f"**Service: {service_name}**\n"
            f"- Status: {status}\n\n"
            f"Select an action:"
        )
        keyboard = [
            [
                InlineKeyboardButton("Start", callback_data=f"start_{service_name}"),
                InlineKeyboardButton("Stop", callback_data=f"stop_{service_name}"),
                InlineKeyboardButton("Restart", callback_data=f"restart_{service_name}"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="services_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif any(query.data.startswith(x) for x in ["start_", "stop_", "restart_"]):
        action, service_name = query.data.split("_")
        result = manage_service(service_name, action)
        text = (
            f"**Service: {service_name}**\n"
            f"- Action: {action}\n\n"
            f"{result}"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="services_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

        ########################### security section #######################

    if query.data == "security_main":
        keyboard = [
            [
                InlineKeyboardButton("🛡 Unblock All IPs", callback_data="unblock_all_ips"),
                InlineKeyboardButton("🔥 View DDoS Attacks", callback_data="view_ddos")
            ],
            [
                InlineKeyboardButton("🚫 View Blocked IPs", callback_data="view_blocked_ips"),
                InlineKeyboardButton("🔓 Unblock IP", callback_data="unblock_ip_menu")
            ],
            [
                InlineKeyboardButton("⚙️ Security Settings", callback_data="security_settings")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🔐 **Security Menu**\nChoose an option:", reply_markup=reply_markup)

    elif query.data == "unblock_all_ips":
        # Function to unblock all IPs
        blocked_ips = get_blocked_ips()
        if blocked_ips:
            for ip in blocked_ips:
                unblock_ip(ip)  # Unblock all IPs
            text = "✅ All blocked IPs have been unblocked successfully."
        else:
            text = "✅ No blocked IPs to unblock."
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="security_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    elif query.data == "view_ddos":
        text = "**🔥 Detected DDoS Attacks:**\n"
        result = subprocess.run(["netstat", "-tn"], stdout=subprocess.PIPE, text=True)
        ip_counts = defaultdict(int)
        for line in result.stdout.split("\n"):
            match = re.search(r"(\d+\.\d+\.\d+\.\d+):\d+", line)
            if match:
                ip = match.group(1)
                ip_counts[ip] += 1

        if ip_counts:
            for ip, count in ip_counts.items():
                if count > 50:
                    text += f"🚨 IP `{ip}` - Connections: `{count}`\n"
        else:
            text += "✅ No DDoS attack detected."
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="security_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    elif query.data == "view_blocked_ips":
        blocked_ips = get_blocked_ips()
        if blocked_ips:
            text = "**🚫 Blocked IPs:**\n"
            text += "\n".join([f"🔴 `{ip}`" for ip in blocked_ips])
        else:
            text = "✅ No blocked IPs found."

        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="security_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    


    elif query.data == "unblock_ip_menu":
        await query.edit_message_text("Send the IP address you want to unblock:")
        context.user_data['awaiting_unblock_ip'] = True

    elif query.data == "security_settings":
        keyboard = [
            [
                InlineKeyboardButton("⚠️ Change Brute Force Threshold", callback_data="change_brute_force_threshold")],
                [
                InlineKeyboardButton("⚠️ Change DDoS Threshold", callback_data="change_ddos_threshold")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="security_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("⚙️ **Security Settings**\nAdjust thresholds:", reply_markup=reply_markup)

    elif query.data == "change_brute_force_threshold":
        await query.edit_message_text("Send the new SSH Brute Force detection threshold (e.g., 5 attempts):")
        context.user_data['awaiting_brute_force_threshold'] = True

    elif query.data == "change_ddos_threshold":
        await query.edit_message_text("Send the new DDoS detection threshold (e.g., 50 connections):")
        context.user_data['awaiting_ddos_threshold'] = True


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle adding service name
    if context.user_data.get('awaiting_service_name'):
        service_name = update.message.text
        services.append(service_name)
        context.user_data['awaiting_service_name'] = False
        await update.message.reply_text(f"Service `{service_name}` added successfully!", parse_mode="Markdown")
        return

    # Handle adding user to allowed_users
    if context.user_data.get('awaiting_user_to_add'):
        user_identifier = update.message.text.strip()
        # Check if numeric
        if user_identifier.isdigit():
            allowed_users.add(int(user_identifier))
            await update.message.reply_text(f"User with chat ID {user_identifier} allowed.")
        else:
            allowed_users.add(user_identifier)
            await update.message.reply_text(f"User with username '{user_identifier}' allowed.")
        context.user_data['awaiting_user_to_add'] = False
        return

    # Handle setting thresholds
    if context.user_data.get('awaiting_threshold_resource'):
        resource = context.user_data['awaiting_threshold_resource']
        try:
            val = int(update.message.text.strip())
            if val < 0 or val > 100:
                await update.message.reply_text("Please provide a valid percentage between 0 and 100.")
            else:
                thresholds[resource] = val
                await update.message.reply_text(f"{resource.capitalize()} threshold set to {val}%!")
        except ValueError:
            await update.message.reply_text("Please provide a numeric value for the threshold.")
        context.user_data['awaiting_threshold_resource'] = None


    # بررسی و آنبلاک کردن IP
    if context.user_data.get('awaiting_unblock_ip'):
        ip = update.message.text.strip()

        # بررسی فرمت IP
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            await update.message.reply_text("❌ **The entered IP format is not valid.** Please enter a correct IP address.", parse_mode="Markdown")
            context.user_data['awaiting_unblock_ip'] = False  # غیرفعال کردن درخواست
            return

        # بررسی عدم بلاک کردن IP خود سرور
        if ip == "77.83.203.147":
            await update.message.reply_text("🚫 **You cannot unblock the server's IP!**", parse_mode="Markdown")
            context.user_data['awaiting_unblock_ip'] = False  # غیرفعال کردن درخواست
            return

        # آنبلاک کردن IP
        unblock_ip(ip)
        await update.message.reply_text(f"✅ **IP `{ip}` has been successfully unblocked.**", parse_mode="Markdown")
        context.user_data['awaiting_unblock_ip'] = False  # غیرفعال کردن درخواست  

    elif context.user_data.get('awaiting_brute_force_threshold'):
        FAILED_ATTEMPTS_THRESHOLD = int(update.message.text.strip())
        await update.message.reply_text(f"✅ Brute Force threshold set to `{FAILED_ATTEMPTS_THRESHOLD}` attempts.", parse_mode="Markdown")
        context.user_data['awaiting_brute_force_threshold'] = False

    elif context.user_data.get('awaiting_ddos_threshold'):
        DDoS_CONNECTION_THRESHOLD = int(update.message.text.strip())
        await update.message.reply_text(f"✅ DDoS threshold set to `{DDoS_CONNECTION_THRESHOLD}` connections.", parse_mode="Markdown")
        context.user_data['awaiting_ddos_threshold'] = False


async def collect_data():
    """ جمع‌آوری داده‌های لحظه‌ای برای نمودارهای ۶۰ ثانیه‌ای """
    print("📊 Collecting real-time resource data...")
    while True:
        async with lock:
            cpu_data.append(psutil.cpu_percent(interval=1))
            memory_data.append(psutil.virtual_memory().percent)
            disk_data.append(psutil.disk_usage('/').percent)
        await asyncio.sleep(1)  # هر ۱ ثانیه یکبار داده‌ها ثبت شوند


# async def collect_data():
#     print("📊 Collecting daily resource data...")  # 👈 این خط را اضافه کنید
#     while True:
#         async with lock:
#             cpu_data.append(psutil.cpu_percent(interval=1))
#             memory_data.append(psutil.virtual_memory().percent)
#             disk_data.append(psutil.disk_usage('/').percent)
#         await asyncio.sleep(1)


async def check_alerts(app: Application):
    while True:
        await asyncio.sleep(300)  # Check every 5 minutes
        # If thresholds are set, check usage
        cpu_usage = psutil.cpu_percent(interval=1)
        mem_usage = psutil.virtual_memory().percent
        disk_usage = psutil.disk_usage('/').percent

        usage_map = {
            "cpu": cpu_usage,
            "memory": mem_usage,
            "disk": disk_usage
        }

        for resource, threshold in thresholds.items():
            if threshold is not None:
                usage = usage_map[resource]
                if usage > threshold:
                    # Trigger alert every time usage is above threshold
                    await send_alert(app, resource, usage, threshold)
                elif usage <= threshold:
                    # Reset alert state when usage is back under the threshold
                    alert_states[resource] = False



async def send_alert(app: Application, resource: str, usage: float, threshold: int):
    msg = f"⚠️ *Alert!*\n {resource.capitalize()} usage is {usage:.2f}%, above the threshold of {threshold}%."
    # Send to admin
    await app.bot.send_message(chat_id=ADMIN_USER_ID, text=msg)
    # Send to all allowed users who have chat IDs
    for user in allowed_users:
        if isinstance(user, int):
            try:
                await app.bot.send_message(chat_id=user, text=msg)
            except:
                pass  # In case user blocked the bot or can't receive messages

def main():
    application = Application.builder().token(TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cmd", execute_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

###############  file management ##########
    application.add_handler(CallbackQueryHandler(file_management_menu, pattern="file_management"))
    application.add_handler(CallbackQueryHandler(list_files, pattern="list_files"))
    application.add_handler(CallbackQueryHandler(send_file, pattern="get_file_"))
    application.add_handler(CallbackQueryHandler(delete_file_menu, pattern="delete_file_menu"))
    application.add_handler(CallbackQueryHandler(delete_file, pattern="delete_file_"))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))


    # اجرای `monitor_ssh_log` در یک **Thread جداگانه**
    ssh_thread = threading.Thread(target=lambda: asyncio.run(monitor_ssh_log(application)), daemon=True)
    ssh_thread.start()

    # Background tasks
    loop = asyncio.get_event_loop()
    loop.create_task(collect_data())  # اجرای جمع‌آوری داده‌ها
    loop.create_task(check_alerts(application))  # اجرای بررسی هشدارها
    loop.create_task(collect_daily_data())  # اجرای جمع‌آوری داده‌های ۲۴ ساعت اخیر #daily report
    
    application.run_polling()

if __name__ == "__main__":
    main()

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

TOKEN = "your_telegrambot_token"

ADMIN_USER_ID = 1234567890  

DEFAULT_FILE_PATH = "/var/www/html/" 

# Set of allowed users. Can contain integers (chat IDs) and strings (usernames).
allowed_users = set()

# # Bufers to store data for the last minute
# cpu_data = deque(maxlen=60)  # Store up to 60 entries (1 per second)
# memory_data = deque(maxlen=60)
# disk_data = deque(maxlen=60)
cpu_data = {
    "1m": deque(maxlen=60),      # 1 minute (60 seconds)
    "5m": deque(maxlen=60),     # 5 minutes (300 seconds)
    "1h": deque(maxlen=60),    # 1 hour (3600 seconds)
    "12h": deque(maxlen=60),  # 12 hours (43200 seconds)
    "1d": deque(maxlen=60)    # 1 day (86400 seconds)
}
memory_data = {
    "1m": deque(maxlen=60),
    "5m": deque(maxlen=60),
    "1h": deque(maxlen=60),
    "12h": deque(maxlen=60),
    "1d": deque(maxlen=60)
}
disk_data = {
    "1m": deque(maxlen=60),
    "5m": deque(maxlen=60),
    "1h": deque(maxlen=60),
    "12h": deque(maxlen=60),
    "1d": deque(maxlen=60)
}

# Define sampling intervals in seconds
SAMPLING_INTERVALS = {
    "1m": 1,      # 1 second
    "5m": 5,      # 5 seconds
    "1h": 60,     # 1 minute
    "12h": 720,   # 12 minutes
    "1d": 1440    # 24 minutes
}
# Update the chart intervals definition
CHART_INTERVALS = {
    "1m": "1 Minute",
    "5m": "5 Minutes",
    "1h": "1 Hour",
    "12h": "12 Hours",
    "1d": "1 Day"
}


lock = asyncio.Lock()  # Lock to ensure only one task runs at a time

services = [] 

# Threshold intervals in seconds
alert_intervals = {
    "cpu": 300,    # Default 5 minutes
    "memory": 300,
    "disk": 300
}

# Last alert times to track intervals
last_alert_times = {
    "cpu": 0,
    "memory": 0,
    "disk": 0
}

# Available interval options
INTERVAL_OPTIONS = {
    "1m": 60,
    "5m": 300,
    "30m": 1800,
    "1h": 3600,
    "12h": 43200,
    "1d": 86400
}

# threshold for alerting
thresholds = {
    "cpu": None,
    "memory": None,
    "disk": None
}

alert_states = {
    "cpu": False,
    "memory": False,
    "disk": False
}

# get data for monitoring section

def get_cpu_details():
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count(logical=True)
    return {"percent": cpu_percent, "count": cpu_count}

def get_memory_details():
    memory = psutil.virtual_memory()
    return {
        "total": memory.total // (1024 * 1024),  
        "used": memory.used // (1024 * 1024),
        "percent": memory.percent,
    }

def get_disk_details():
    disk = psutil.disk_usage('/')
    return {
        "total": disk.total // (1024 * 1024), 
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

########################################################    


### top process

import psutil

def get_top_processes(sort_by="cpu", limit=5):
    """
    Get top processes sorted by CPU or memory usage.
    
    Args:
        sort_by (str): 'cpu' or 'memory' to determine sorting criteria.
        limit (int): Number of processes to return.
    Returns:
        list: List of dictionaries containing process details.
    """
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            processes.append({
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'cpu': proc.info['cpu_percent'],
                'memory': proc.info['memory_percent']
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if sort_by == "cpu":
        return sorted(processes, key=lambda x: x['cpu'], reverse=True)[:limit]
    elif sort_by == "memory":
        return sorted(processes, key=lambda x: x['memory'], reverse=True)[:limit]
    return processes[:limit]


# status for manage services

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

#******************Network ***************************************************
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
                try:
                    ping_str = line.split(":")[1].strip().split(" ")[0]
                    ping = float(ping_str)
                except:
                    pass
            elif line.startswith("Download:"):
                try:
                    download_str = line.split(":")[1].strip().split(" ")[0]
                    download = float(download_str)
                except:
                    pass
            elif line.startswith("Upload:"):
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
            error_msg = result.stderr.strip()
        else:
            error_msg = None

        output = result.stdout
        packet_loss_line = [line for line in output.split("\n") if "packet loss" in line]
        if not packet_loss_line:
            return None, error_msg or "Could not parse packet loss"

        line = packet_loss_line[0]
        try:
            loss_part = line.split(",")[2].strip()  
            loss_value_str = loss_part.split("%")[0].strip()
            packet_loss = float(loss_value_str)
            return packet_loss, error_msg
        except:
            return None, error_msg or "Could not parse packet loss"
    except Exception as e:
        return None, str(e)


################## make chart for monitoring ######################
def generate_chart(data, label, interval):
    plt.figure(figsize=(8, 4))  # Slightly larger for better readability
    
    # Calculate the total duration based on the interval and sampling rate
    total_points = len(data)
    total_duration = total_points * SAMPLING_INTERVALS[interval]
    
    # Generate time points starting from 0 (present) to total_duration (past)
    time_points = list(range(0, total_duration + SAMPLING_INTERVALS[interval], SAMPLING_INTERVALS[interval]))
    
    # Plot the data with reversed time points to match the data order (newest at the right)
    plt.plot(time_points[:len(data)], data, marker='o', label=label)
    plt.title(f'{label} Usage Over Last {CHART_INTERVALS[interval]}')
    
    # Adjust x-axis label based on interval
    if interval in ["1m", "5m"]:
        plt.xlabel('Time Elapsed (Seconds)')
    elif interval == "1h":
        plt.xlabel('Time Elapsed (Minutes)')
    else:  # 12h and 1d
        plt.xlabel('Time Elapsed (Hours)')
    
    plt.ylabel('Usage (%)')
    plt.ylim(0, 100)
    plt.grid(True)
    plt.legend()
    
    # Invert x-axis if desired (optional: to show past on the left, present on the right)
    # plt.gca().invert_xaxis()
    
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
    if user.id == ADMIN_USER_ID:
        return True
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
    "🔐 *Security Monitoring*: Detect and block **suspicious login attempts**, and manage **blocked IPs.**\n"
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

    # If admin, add Manage Users button 
    if update.effective_user.id == ADMIN_USER_ID:
        keyboard.append([InlineKeyboardButton("🔒 Manage Users", callback_data="manage_users_main")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")


################# security functions ###################3

FAILED_ATTEMPTS_THRESHOLD = 5  
AUTH_LOG_PATH = "/var/log/auth.log"  

failed_attempts = defaultdict(int)  # failed attempt for login (ssh)
blocked_ips = set()  


#########   ssh brute force detection  ######################
async def monitor_ssh_log(app: Application):
    print("🔍 ssh monitoring actived ...")

    with subprocess.Popen(["tail", "-F", AUTH_LOG_PATH], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        while True: 
            line = process.stdout.readline()
            if not line:
                await asyncio.sleep(0.1)
                continue

            match = re.search(r"Failed password for .* from (\d+\.\d+\.\d+\.\d+)", line)
            if match:
                ip = match.group(1)
                failed_attempts[ip] += 1
                if failed_attempts[ip] >= FAILED_ATTEMPTS_THRESHOLD:
                    if ip == "77.83.203.147":                     
                        print(f"⚠️ The server IP ({ip}) has been identified, but it will not be blocked.")
                    elif ip not in blocked_ips:
                        print(f"✅ Blocking {ip} ...")
                        await send_security_alert(app, ip, "SSH Brute Force Attack")
                        block_ip(ip)
                        blocked_ips.add(ip)


### send alert to telegram
async def send_security_alert(app: Application, ip: str, attack_type: str):
    msg = f"🚨 **Security Alert!** 🚨\n🔴 Attack Type: `{attack_type}`\n🔍 Suspicious IP: `{ip}`\n⚠️ This IP has been blocked."
    await app.bot.send_message(chat_id=ADMIN_USER_ID, text=msg, parse_mode="Markdown")


### block ip
def block_ip(ip: str):
    if ip == "77.83.203.147":  
        print(f"⚠️ Server IP ({ip}) detected, but it will not be blocked.")
        return
    subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"])
    print(f"⛔ IP {ip} has been blocked.")

### unblock ip
def unblock_ip(ip: str):
    subprocess.run(["sudo", "iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"])
    print(f"✅ IP {ip} has been unblocked.")

### get list of blocked ips

def get_blocked_ips():
    result = subprocess.run(["sudo", "iptables", "-L", "INPUT", "-v", "-n"], stdout=subprocess.PIPE, text=True)
    lines = result.stdout.split("\n")
    blocked_ips = []

    for line in lines:
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)  
        if match and "DROP" in line:  
            blocked_ips.append(match.group(1))

    return blocked_ips


######################################  Daily Report    ######################################
from collections import deque
import datetime


async def reset_daily_data():
    while True:
        now = datetime.datetime.now()
        next_reset_time = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_seconds = (next_reset_time - now).total_seconds()
        
        print(f"⏳ Resetting daily data in {sleep_seconds / 3600:.2f} hours...")

        await asyncio.sleep(sleep_seconds)

        resource_history["cpu"].clear()
        resource_history["memory"].clear()
        resource_history["disk"].clear()
        resource_history["timestamps"].clear()

        print("✅ Daily resource data has been reset!")


# save resouce usage of server 24 hr past
resource_history = {
    "cpu": deque(maxlen=288),  #(60/5) * 24
    "memory": deque(maxlen=288),
    "disk": deque(maxlen=288),
    "timestamps": deque(maxlen=288)  
}
async def collect_daily_data():
    print("📊 Collecting daily resource data...")

    while True:
        cpu_samples = [psutil.cpu_percent(interval=1)]
        memory_samples = [psutil.virtual_memory().percent]
        disk_samples = [psutil.disk_usage('/').percent]

        # check empty lists to prevent division by zero
        avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else psutil.cpu_percent(interval=1)
        avg_memory = sum(memory_samples) / len(memory_samples) if memory_samples else psutil.virtual_memory().percent
        avg_disk = sum(disk_samples) / len(disk_samples) if disk_samples else psutil.disk_usage('/').percent
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        resource_history["cpu"].append(avg_cpu)
        resource_history["memory"].append(avg_memory)
        resource_history["disk"].append(avg_disk)
        resource_history["timestamps"].append(timestamp)

        print(f"✅ Data saved: {timestamp} - CPU: {avg_cpu:.2f}%, Memory: {avg_memory:.2f}%, Disk: {avg_disk:.2f}%")

        await asyncio.sleep(300)  #after 5 min


# make daily report csv file
import os
def generate_daily_report_csv():

    report_dir = "/root/MonitoringBot/reports"  
    csv_filename = "server_daily_report.csv"
    csv_path = os.path.join(report_dir, csv_filename)  

    if not resource_history["cpu"]:  # If no data exists, initialize the values
        print("⚠️ No data found, recording initial resource data...")
        return None  

    # average datas
    avg_cpu = sum(resource_history["cpu"]) / len(resource_history["cpu"]) if resource_history["cpu"] else psutil.cpu_percent()
    avg_memory = sum(resource_history["memory"]) / len(resource_history["memory"]) if resource_history["memory"] else psutil.virtual_memory().percent
    avg_disk = sum(resource_history["disk"]) / len(resource_history["disk"]) if resource_history["disk"] else psutil.disk_usage('/').percent

    df_resources = pd.DataFrame({
        "Metric": ["Avg CPU Usage (%)", "Avg Memory Usage (%)", "Avg Disk Usage (%)"],
        "Value": [avg_cpu, avg_memory, avg_disk]
    })
    
    df_history = pd.DataFrame({
        "Timestamp": list(resource_history["timestamps"]),
        "CPU Usage (%)": list(resource_history["cpu"]),
        "Memory Usage (%)": list(resource_history["memory"]),
        "Disk Usage (%)": list(resource_history["disk"])
    })

    df_resources.to_csv(csv_path, index=False)
    df_history.to_csv(csv_path, index=False, mode='a') 

    print(f"📄 Daily report generated successfully at {csv_path}")
    return csv_path  


async def send_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_authorized_user(update):  #updated
        await update.callback_query.answer("⛔ You are not authorized to request this report.", show_alert=True)
        return

    await update.callback_query.answer("⏳ Generating report...", show_alert=False)

    if len(resource_history["cpu"]) < 1:  
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

    csv_path = generate_daily_report_csv()

    if not csv_path or not os.path.exists(csv_path):
        await update.callback_query.message.reply_text("⚠️ **Report file not found!**\nTry again later.", parse_mode="Markdown")
        return

    print(f"📂 Checking file path: {csv_path}")

    try:
        with open(csv_path, "rb") as file:
            await context.bot.send_document(chat_id=update.effective_user.id, document=file, filename=os.path.basename(csv_path)) 

        await update.callback_query.message.reply_text("✅ **Daily report sent successfully!**", parse_mode="Markdown")

    except Exception as e:
        print(f"⚠️ Error sending file: {e}")
        await update.callback_query.message.reply_text(f"❌ **Failed to send report:** {str(e)}", parse_mode="Markdown")



######################################### File management  ###################################

async def file_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    files = os.listdir(DEFAULT_FILE_PATH)
    if not files:
        await update.callback_query.message.edit_text("📂 No files found in `/var/www/html/`.")
        return

    file_buttons = [[InlineKeyboardButton(f"📄 {file}", callback_data=f"get_file_{file}")] for file in files]
    file_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="file_management")])

    reply_markup = InlineKeyboardMarkup(file_buttons)
    await update.callback_query.message.edit_text("📂 **Available Files:**\nSelect a file to download:", reply_markup=reply_markup, parse_mode="Markdown")


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    filename = query.data.split("get_file_")[1]
    file_path = os.path.join(DEFAULT_FILE_PATH, filename)

    if os.path.exists(file_path):
        await context.bot.send_document(chat_id=update.effective_user.id, document=open(file_path, "rb"), filename=filename)
        await query.answer("📄 File sent successfully!", show_alert=True)
    else:
        await query.answer("⚠️ File not found!", show_alert=True)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized_user(update):
        await update.message.reply_text("⛔ You are not authorized to upload files.")
        return

    if 'awaiting_file_upload' not in context.user_data or not context.user_data['awaiting_file_upload']:
        await update.message.reply_text("❌ Please use the '📤 Upload File' option first.")
        return

    file = update.message.document
    file_name = file.file_name
    file_path = os.path.join(DEFAULT_FILE_PATH, file_name)

    file_obj = await context.bot.get_file(file.file_id)  
    
    await file_obj.download_to_drive(file_path)

    context.user_data['awaiting_file_upload'] = False 
    await update.message.reply_text(f"✅ File `{file_name}` saved successfully in `/var/www/html/`!", parse_mode="Markdown")


async def delete_file_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = os.listdir(DEFAULT_FILE_PATH)
    if not files:
        await update.callback_query.message.edit_text("📂 No files available to delete.")
        return

    file_buttons = [[InlineKeyboardButton(f"🗑 {file}", callback_data=f"delete_file_{file}")] for file in files]
    file_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="file_management")])

    reply_markup = InlineKeyboardMarkup(file_buttons)
    await update.callback_query.message.edit_text("🗑 **Select a file to delete:**", reply_markup=reply_markup, parse_mode="Markdown")

async def delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


ALLOWED_COMMANDS = ["ls", "df", "uptime", "free", "tail", "ps aux", "whoami", "cat"]
async def execute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_authorized_user(update):
        await update.message.reply_text("⛔ You are not authorized to execute commands.")
        return

    if not context.args:
        await update.message.reply_text("❌ Please provide a command. Example: `/cmd uptime`", parse_mode="Markdown")
        return

    command = " ".join(context.args)

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

    if command.split()[0] not in [cmd.split()[0] for cmd in ALLOWED_COMMANDS]:
        await update.message.reply_text(f"🚫 Command `{command}` is not allowed.", parse_mode="Markdown")
        return

    try:
        result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        
        output = result.stdout.strip() if result.stdout else result.stderr.strip()
        
        if len(output) > 4000:
            # long output, send as a file
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
            [   InlineKeyboardButton("Process", callback_data="process"),               
                 
            ],
            [
                InlineKeyboardButton("🔙  Back", callback_data="back_to_main"),             
                 
            ]
            ,
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select a resource to monitor:", reply_markup=reply_markup)
    
    elif query.data in ["cpu", "memory", "disk"]:
        resource = query.data
        keyboard = [
            [
                InlineKeyboardButton("1m", callback_data=f"chart_{resource}_1m"),
                InlineKeyboardButton("5m", callback_data=f"chart_{resource}_5m"),
                InlineKeyboardButton("1h", callback_data=f"chart_{resource}_1h"),
            ],
            [
                InlineKeyboardButton("12h", callback_data=f"chart_{resource}_12h"),
                InlineKeyboardButton("1d", callback_data=f"chart_{resource}_1d"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Select time interval for {resource.capitalize()} usage chart:",
            reply_markup=reply_markup
        )

    elif query.data.startswith("chart_"):
        parts = query.data.split("_")
        resource = parts[1]
        interval = parts[2]
        
        if resource == "cpu":
            data = cpu_data[interval]
            details = get_cpu_details()
            text = (
                f"**CPU Usage Over Last {CHART_INTERVALS[interval]}:**\n"
                f"- Total Cores: {details['count']} cores\n"
                f"- Current Usage: {data[-1] if data else 0:.2f}%\n"
            )
        elif resource == "memory":
            data = memory_data[interval]
            details = get_memory_details()
            text = (
                f"**Memory Usage Over Last {CHART_INTERVALS[interval]}:**\n"
                f"- Total: {details['total']} MB\n"
                f"- Used: {details['used']} MB ({data[-1] if data else 0:.2f}%)\n"
            )
        elif resource == "disk":
            data = disk_data[interval]
            details = get_disk_details()
            text = (
                f"**Disk Usage Over Last {CHART_INTERVALS[interval]}:**\n"
                f"- Total: {details['total']} MB\n"
                f"- Used: {details['used']} MB ({data[-1] if data else 0:.2f}%)\n"
            )

        # Generate and send the chart
        chart_buf = generate_chart(list(data), resource.capitalize(), interval)
        await query.message.reply_photo(photo=chart_buf)

        # Send the text with back button
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

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
        await query.edit_message_text("Choose an action to manage your services:", reply_markup=reply_markup)

    elif query.data == "manage_users_main":
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
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage users.")
            return

        await query.edit_message_text("Please send the username or chat ID of the user you want to add.")
        context.user_data['awaiting_user_to_add'] = True

    elif query.data == "remove_user_menu":
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


    elif query.data == "packet_loss":
        loss, err = get_packet_loss()
        if err:
            text = f"Error measuring packet loss: `{err}`"
        else:
            text = f"**Packet Loss**: {loss}%"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="networking_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)   
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


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

        if query.from_user.id == ADMIN_USER_ID:
            keyboard.append([InlineKeyboardButton("🔒 Manage Users", callback_data="manage_users_main")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select a category:", reply_markup=reply_markup)

############### daily report ###################
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
        await query.message.reply_text("📤 Please send the desired file to be stored in the /var/www/html/ directory.")
        context.user_data['awaiting_file_upload'] = True  # File reception mode is enabled.

        



##############

    elif query.data == "alerting_main":
        if query.from_user.id == ADMIN_USER_ID:
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
            keyboard = [[InlineKeyboardButton("🔙  Back", callback_data="back_to_main")]]

        reply_markup = InlineKeyboardMarkup(keyboard)
        cpu_interval = [k for k, v in INTERVAL_OPTIONS.items() if v == alert_intervals['cpu']][0]
        mem_interval = [k for k, v in INTERVAL_OPTIONS.items() if v == alert_intervals['memory']][0]
        disk_interval = [k for k, v in INTERVAL_OPTIONS.items() if v == alert_intervals['disk']][0]
        
        await query.edit_message_text(
            f"Current Thresholds:\n"
            f"CPU: {thresholds['cpu']}% (Interval: {cpu_interval})\n"
            f"Memory: {thresholds['memory']}% (Interval: {mem_interval})\n"
            f"Disk: {thresholds['disk']}% (Interval: {disk_interval})\n\n",
            reply_markup=reply_markup
        )

    elif query.data in ["set_cpu_threshold", "set_memory_threshold", "set_disk_threshold"]:
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage alerts.")
            return

        resource = query.data.split("_")[1]
        context.user_data['awaiting_threshold_resource'] = resource
        #await query.edit_message_text(f"Please send the {resource.capitalize()} threshold in percent (e.g. 80):")
        # Create interval selection buttons
        interval_buttons = [
            [
                InlineKeyboardButton("1m", callback_data=f"interval_{resource}_1m"),
                InlineKeyboardButton("5m", callback_data=f"interval_{resource}_5m"),
                InlineKeyboardButton("30m", callback_data=f"interval_{resource}_30m")
            ],
            [
                InlineKeyboardButton("1h", callback_data=f"interval_{resource}_1h"),
                InlineKeyboardButton("12h", callback_data=f"interval_{resource}_12h"),
                InlineKeyboardButton("1d", callback_data=f"interval_{resource}_1d")
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data=f"alerting_main")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(interval_buttons)
        await query.edit_message_text(
            f"Select alert interval for {resource.capitalize()} threshold:",
            reply_markup=reply_markup
        )

    elif query.data.startswith("interval_"):
        parts = query.data.split("_")
        resource = parts[1]
        interval_key = parts[2]
        
        context.user_data['awaiting_threshold_resource'] = resource
        context.user_data['selected_interval'] = INTERVAL_OPTIONS[interval_key]
        await query.edit_message_text(
            f"Interval set to {interval_key}. Now please send the {resource.capitalize()} threshold in percent (e.g. 80):"
        )


    elif query.data in ["remove_cpu_threshold", "remove_memory_threshold", "remove_disk_threshold"]:
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("You are not authorized to manage alerts.")
            return

        resource = query.data.split("_")[1]
        thresholds[resource] = None
        alert_states[resource] = False  # Reset alert state if removing threshold
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="alerting_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"{resource.capitalize()} threshold removed.\n",
            reply_markup=reply_markup
        )
  
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

### top processes
    elif query.data == "process":
            keyboard = [
                [
                    InlineKeyboardButton("Top CPU", callback_data="top_cpu"),
                    InlineKeyboardButton("Top Memory", callback_data="top_memory"),
                ],
                [InlineKeyboardButton("🔙 Back", callback_data="monitoring_main")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("Select how to view processes:", reply_markup=reply_markup)

    elif query.data in ["top_cpu", "top_memory"]:
        sort_by = "cpu" if query.data == "top_cpu" else "memory"
        top_procs = get_top_processes(sort_by=sort_by)
        
        text = f"**Top 5 Processes by {'CPU' if sort_by == 'cpu' else 'Memory'} Usage:**\n\n"
        keyboard = []
        for proc in top_procs:
            text += (
                f"PID: `{proc['pid']}` | Name: `{proc['name']}` | "
                f"CPU: `{proc['cpu']:.1f}%` | Mem: `{proc['memory']:.1f}%`\n"
            )
            keyboard.append([InlineKeyboardButton(
                f"Kill PID {proc['pid']}", callback_data=f"kill_process_{proc['pid']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="process")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")

    elif query.data.startswith("kill_process_"):
        pid = int(query.data.split("_")[2])
        # درخواست تأیید
        keyboard = [
            [InlineKeyboardButton("✅ Yes", callback_data=f"confirm_kill_{pid}"),
             InlineKeyboardButton("❌ No", callback_data="process")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ Are you sure you want to kill process with PID `{pid}`?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif query.data.startswith("confirm_kill_"):
        pid = int(query.data.split("_")[2])
        try:
            process = psutil.Process(pid)
            process.terminate()  
            if process.is_running():
                process.kill()  
            text = f"✅ Process with PID `{pid}` has been terminated."
        except psutil.NoSuchProcess:
            text = f"❌ Process with PID `{pid}` not found."
        except psutil.AccessDenied:
            text = f"❌ Permission denied to kill process with PID `{pid}`."
        except Exception as e:
            text = f"⚠️ Error killing process `{pid}`: {str(e)}"
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="process")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


        ########################### security section #######################

    if query.data == "security_main":
        keyboard = [
            [
                InlineKeyboardButton("🛡 Unblock All IPs", callback_data="unblock_all_ips")
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
        await query.edit_message_text("🔐 **Security Menu**\nChoose an option:", reply_markup=reply_markup , parse_mode="Markdown")

    elif query.data == "unblock_all_ips":
        blocked_ips = get_blocked_ips()
        if blocked_ips:
            for ip in blocked_ips:
                unblock_ip(ip)  
            text = "✅ All blocked IPs have been unblocked successfully."
        else:
            text = "✅ No blocked IPs to unblock."
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="security_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    elif query.data == "view_blocked_ips":
        blocked_ips = get_blocked_ips()
        if blocked_ips:
            text = "**🚫 Blocked IPs:**\n"
            ip_list = "\n".join([f"🔴 `{ip}`" for ip in blocked_ips])
            full_text = text + ip_list
            
            # Telegram message limit is 4096 characters
            MAX_MESSAGE_LENGTH = 4096
            
            if len(full_text) <= MAX_MESSAGE_LENGTH:
                # If the message fits, send it as is
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="security_main")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(full_text, reply_markup=reply_markup, parse_mode="Markdown")
            else:
                # Split the message into chunks
                messages = []
                current_message = text
                for line in ip_list.split("\n"):
                    if len(current_message) + len(line) + 1 < MAX_MESSAGE_LENGTH:
                        current_message += line + "\n"
                    else:
                        messages.append(current_message.strip())
                        current_message = text + line + "\n"
                if current_message.strip():
                    messages.append(current_message.strip())
                
                # Send each chunk as a separate message
                keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="security_main")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(messages[0], reply_markup=reply_markup, parse_mode="Markdown")
                for msg in messages[1:]:
                    await query.message.reply_text(msg, parse_mode="Markdown")
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

            [InlineKeyboardButton("🔙 Back", callback_data="security_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("⚙️ **Security Settings**\nAdjust thresholds:", reply_markup=reply_markup, parse_mode="Markdown")

    elif query.data == "change_brute_force_threshold":
        await query.edit_message_text("Send the new SSH Brute Force detection threshold (e.g., 5 attempts):")
        context.user_data['awaiting_brute_force_threshold'] = True



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
        # Check if number
        if user_identifier.isdigit():
            allowed_users.add(int(user_identifier))
            await update.message.reply_text(f"User with chat ID {user_identifier} allowed.")
        else:
            allowed_users.add(user_identifier)
            await update.message.reply_text(f"User with username '{user_identifier}' allowed.")
        context.user_data['awaiting_user_to_add'] = False
        return

    if context.user_data.get('awaiting_threshold_resource'):
        resource = context.user_data['awaiting_threshold_resource']
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="alerting_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            val = int(update.message.text.strip())
            if val < 0 or val > 100:
                await update.message.reply_text(
                    "Please provide a valid percentage between 0 and 100.",
                    reply_markup=reply_markup
                )
            else:
                thresholds[resource] = val
                if 'selected_interval' in context.user_data:
                    alert_intervals[resource] = context.user_data['selected_interval']
                    interval_str = [k for k, v in INTERVAL_OPTIONS.items() if v == context.user_data['selected_interval']][0]
                    await update.message.reply_text(
                        f"{resource.capitalize()} threshold set to {val}% with {interval_str} alert interval!\n",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        f"{resource.capitalize()} threshold set to {val}%!\n",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    
        except ValueError:
            await update.message.reply_text(
                "Please provide a numeric value for the threshold.",
                reply_markup=reply_markup
            )
        context.user_data['awaiting_threshold_resource'] = None
        context.user_data.pop('selected_interval', None)
        return


    # check ip and unblock
    if context.user_data.get('awaiting_unblock_ip'):
        ip = update.message.text.strip()

        # check ip format
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            await update.message.reply_text("❌ **The entered IP format is not valid.** Please enter a correct IP address.", parse_mode="Markdown")
            context.user_data['awaiting_unblock_ip'] = False  
            return

        # dont block ip of server
        if ip == "77.83.203.147":
            await update.message.reply_text("🚫 **You cannot unblock the server's IP!**", parse_mode="Markdown")
            context.user_data['awaiting_unblock_ip'] = False  
            return

        # unblock ip
        unblock_ip(ip)
        await update.message.reply_text(f"✅ **IP `{ip}` has been successfully unblocked.**", parse_mode="Markdown")
        context.user_data['awaiting_unblock_ip'] = False   

    elif context.user_data.get('awaiting_brute_force_threshold'):
        FAILED_ATTEMPTS_THRESHOLD = int(update.message.text.strip())
        await update.message.reply_text(f"✅ Brute Force threshold set to `{FAILED_ATTEMPTS_THRESHOLD}` attempts.", parse_mode="Markdown")
        context.user_data['awaiting_brute_force_threshold'] = False



# collect data after 1 second for chart
async def collect_data():
    print("📊 Collecting real-time resource data...")
    last_collection = {
        "1m": 0,
        "5m": 0,
        "1h": 0,
        "12h": 0,
        "1d": 0
    }
    
    while True:
        current_time = time.time()
        
        async with lock:
            cpu_usage = psutil.cpu_percent(interval=1)
            mem_usage = psutil.virtual_memory().percent
            disk_usage = psutil.disk_usage('/').percent
            
            # Collect data for each interval based on its sampling rate
            for interval in CHART_INTERVALS.keys():
                if current_time - last_collection[interval] >= SAMPLING_INTERVALS[interval]:
                    cpu_data[interval].append(cpu_usage)
                    memory_data[interval].append(mem_usage)
                    disk_data[interval].append(disk_usage)
                    last_collection[interval] = current_time
        
        # Sleep for the shortest interval (1 second)
        await asyncio.sleep(1)

async def check_alerts(app: Application):
    while True:
        await asyncio.sleep(60)  # Check every minute
        current_time = time.time()
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
                time_since_last_alert = current_time - last_alert_times[resource]
                
                if usage > threshold and time_since_last_alert >= alert_intervals[resource]:
                    await send_alert(app, resource, usage, threshold)
                    last_alert_times[resource] = current_time
                elif usage <= threshold:
                    alert_states[resource] = False



async def send_alert(app: Application, resource: str, usage: float, threshold: int):
    msg = f"""
⚠️ *Alert! Critical Usage Detected!*

The *{resource.capitalize()}* usage has exceeded the threshold:

🔹 Current Usage: `{usage:.2f}%`
🔹 Threshold: `{threshold}%`

Please take immediate action to prevent potential issues.

— *System Monitoring Alert* 🛑
"""
    # Send to admin
    await app.bot.send_message(chat_id=ADMIN_USER_ID, text=msg, parse_mode="Markdown")

    # Send to all allowed users who have chat IDs
    for user in allowed_users:
        if isinstance(user, int):
            try:
                await app.bot.send_message(chat_id=user, text=msg, parse_mode="Markdown")
            except:
                pass

def main():
    application = Application.builder().token(TOKEN).build()

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


    # Run monitor_ssh_log in a separate thread.
    ssh_thread = threading.Thread(target=lambda: asyncio.run(monitor_ssh_log(application)), daemon=True)
    ssh_thread.start()

    # Background tasks
    loop = asyncio.get_event_loop()
    loop.create_task(collect_data())  # data collect -> for monitoring chart
    loop.create_task(check_alerts(application))  # check alerts
    loop.create_task(collect_daily_data())  # collect data for daily report
    loop.create_task(reset_daily_data())  # reset data of daily report after 1 day
    
    application.run_polling()

if __name__ == "__main__":
    main()

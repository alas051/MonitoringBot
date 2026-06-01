# Linux Server Monitoring Telegram Bot

A powerful open-source Telegram bot for monitoring, managing, and securing Linux servers directly from chat.

Monitor server health, control services, receive alerts, inspect network status, manage files, and run safe Linux commands — all from Telegram.

![License](https://img.shields.io/github/license/alas051/MonitoringBot)
![Python](https://img.shields.io/badge/python-3.7%2B-blue)
![Platform](https://img.shields.io/badge/platform-linux-success)
![Stars](https://img.shields.io/github/stars/alas051/MonitoringBot?style=social)

---

## Why this project?

Managing a Linux server often means switching between SSH sessions, monitoring dashboards, logs, and alerting tools.

**MonitoringBot** brings the most important server operations into Telegram, so you can:

- check your server status in seconds
- get notified before issues become outages
- manage services remotely
- monitor suspicious login attempts
- receive performance reports without opening multiple tools

It is designed for developers, sysadmins, VPS owners, and anyone who wants a lightweight, practical server assistant inside Telegram.

---

## Features

### 📊 Server Monitoring
- Monitor **CPU, memory, disk usage, and uptime** in real-time
- View performance trends with charts across multiple intervals:
  - `1m`
  - `5m`
  - `1h`
  - `12h`
  - `1d`

### 🛠 Service Management
- Start services
- Stop services
- Restart services
- Check service status
- Add or remove services from the monitoring list

Supports common Linux services such as:
- Nginx
- MySQL
- Apache
- Docker
- and more

### 🌐 Network Tools
- Run speed tests
- Check packet loss
- Monitor network stability and connectivity

### ⚠️ Smart Alerts
- Receive notifications for:
  - high CPU usage
  - low disk space
  - memory pressure
  - other critical server conditions

### 🔐 Security Monitoring
- Detect suspicious login attempts
- View blocked IPs
- Block or manage suspicious IP addresses

### 📄 Daily Reports
- Receive detailed **CSV reports** of server activity and performance over the last 24 hours

### 📂 File Management
- Upload files
- Download files
- Delete files directly from Telegram

### ⌨️ Safe Linux Commands
Run pre-approved commands such as:
- `uptime`
- `df`
- `free`
- and other safe system commands

---


## Use Cases

MonitoringBot is useful for:

- **Sysadmins** who want quick server checks from mobile
- **Developers** managing a VPS or personal server
- **DevOps engineers** who need lightweight Telegram-based alerts
- **Security-conscious users** who want login monitoring and IP blocking
- **Solo founders / indie hackers** who want simple remote server visibility

---

## Feature Overview

| Feature | Status |
|---|---|
| CPU / RAM / Disk monitoring | ✅ |
| Uptime tracking | ✅ |
| Historical charts | ✅ |
| Service management | ✅ |
| Telegram alerts | ✅ |
| Network tools | ✅ |
| Security monitoring | ✅ |
| Daily CSV reports | ✅ |
| File management | ✅ |
| Safe command execution | ✅ |

---

## Installation

### Quick Install

Run the setup script directly on your Linux server:
```bash
bash <(curl -Ls https://raw.githubusercontent.com/alas051/MonitoringBot/main/setup.sh)

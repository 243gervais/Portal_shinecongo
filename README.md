# Shine Congo – Employee Operations Portal

Internal web application for managing Shine Congo employee operations, featuring QR code time tracking, vehicle wash management, and issue reporting.

## 🚀 Features

### For Employees
- ✅ Clock in/out via daily QR code
- ✅ Add washes with photos (before/after)
- ✅ Report issues (equipment, water, security, etc.)
- ✅ View history (time entries, washes, issues)
- ✅ Mobile-first interface optimized for smartphones

### For Managers
- ✅ Dashboard with daily statistics per site
- ✅ Generate and print daily QR codes
- ✅ View time entries with filters
- ✅ Correct time entries with mandatory reason + audit
- ✅ View washes with financial totals
- ✅ Manage reported issues (statuses: Open/In Progress/Resolved)

### For Administrators
- ✅ Full access to all sites
- ✅ User and profile management
- ✅ Complete Django Admin interface
- ✅ Audit log of all actions

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Access to a database (SQLite by default, PostgreSQL recommended in production)

## 🛠️ Local Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd portal_shinecongo
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file at the project root:

```env
DJANGO_SECRET_KEY=your-very-secure-secret-key
DJANGO_SECRET_QR=your-very-secure-qr-secret
DEBUG=True
```

**⚠️ Important:** In production, use strong secrets and never commit the `.env` file!

### 5. Apply migrations

```bash
python manage.py migrate
```

### 6. Create a superuser

```bash
python manage.py createsuperuser
```

Follow the instructions to create your administrator account.

### 7. Start the development server

**⚠️ Important:** Make sure you have activated the virtual environment before starting the server!

```bash
# Activate the virtual environment (if not already done)
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Start the server
python manage.py runserver
```

**Alternative:** Use the provided script that automatically activates the virtual environment:

```bash
./runserver.sh
```

The application will be accessible at: `http://127.0.0.1:8000`

## 📱 Usage

### Login

1. Go to `http://127.0.0.1:8000/login/`
2. Log in with your credentials

### Initial setup (Admin)

1. Log in as administrator
2. Create **Sites** (e.g., Texaco Gombe Station, Total Lemba Station)
3. Create **Users** and assign them:
   - A **Role** (Employee, Manager, Admin)
   - A **Site** (except for Admin who sees all sites)

### For Managers

1. Access the manager dashboard
2. For each site, click on "Today's QR" to generate/display the QR code
3. Print the QR code and place it at the site entrance
4. The QR code automatically changes each day

### For Employees

1. Scan the daily QR code with your phone to clock in
2. Add completed washes with photos
3. At the end of the day, scan the QR code again to clock out and confirm the number of washes

## 🌐 Server Deployment (IP without domain)

### Option 1: Deployment with Gunicorn + Nginx

#### 1. On the server, install system dependencies

```bash
sudo apt update
sudo apt install python3-pip python3-venv nginx
```

#### 2. Clone the project on the server

```bash
cd /opt  # or another appropriate directory
git clone <repo-url> portal_shinecongo
cd portal_shinecongo
```

#### 3. Create the virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 4. Configure environment variables

```bash
nano .env
```

Add:
```env
DJANGO_SECRET_KEY=<production-secret-key>
DJANGO_SECRET_QR=<production-qr-secret>
DEBUG=False
ALLOWED_HOSTS=your-server-ip,127.0.0.1
```

#### 5. Modify `settings.py` for production

Add in `shinecongo/settings.py`:

```python
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "fallback-key")
DEBUG = os.getenv("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",") if os.getenv("ALLOWED_HOSTS") else []
```

#### 6. Apply migrations and collect static files

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

#### 7. Create a systemd service file for Gunicorn

```bash
sudo nano /etc/systemd/system/shinecongo.service
```

Content:
```ini
[Unit]
Description=Shine Congo Gunicorn daemon
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/portal_shinecongo
Environment="PATH=/opt/portal_shinecongo/venv/bin"
ExecStart=/opt/portal_shinecongo/venv/bin/gunicorn --workers 3 --bind unix:/opt/portal_shinecongo/shinecongo.sock shinecongo.wsgi:application

[Install]
WantedBy=multi-user.target
```

#### 8. Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/shinecongo
```

Content:
```nginx
server {
    listen 80;
    server_name your-server-ip;

    location /static/ {
        alias /opt/portal_shinecongo/staticfiles/;
    }

    location /media/ {
        alias /opt/portal_shinecongo/media/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/opt/portal_shinecongo/shinecongo.sock;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/shinecongo /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 9. Start the Gunicorn service

```bash
sudo systemctl start shinecongo
sudo systemctl enable shinecongo
```

### Option 2: Simple deployment with Gunicorn (without Nginx)

For a quick deployment without Nginx:

```bash
# In the project directory
source venv/bin/activate
gunicorn --bind 0.0.0.0:8000 shinecongo.wsgi:application
```

⚠️ **Note:** This method is not recommended for production as it does not serve static files efficiently.

## 🔐 Security

### Important environment variables

- `DJANGO_SECRET_KEY`: Django secret key (generate with `python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'`)
- `DJANGO_SECRET_QR`: Secret key for QR token generation (use a strong random string)
- `DEBUG`: Always `False` in production
- `ALLOWED_HOSTS`: List of authorized domains/IPs (comma-separated)

### Security recommendations

1. ✅ Use HTTPS in production (free Let's Encrypt certificate)
2. ✅ Change default secrets
3. ✅ Configure a firewall (UFW)
4. ✅ Regularly backup the database
5. ✅ Limit SSH access to the server

## 📁 Project Structure

```
portal_shinecongo/
├── comptes/          # Accounts - User and profile management
├── sites/            # Sites - Site/location model
├── pointage/         # Time tracking - QR code time tracking system + ShiftDay
├── lavages/          # Washes - Vehicle wash management
├── problemes/        # Issues - Issue reporting
├── audit/            # Audit log
├── templates/        # HTML templates
├── static/           # Static files (CSS, JS, images)
├── media/            # Uploaded files (photos)
└── shinecongo/       # Django configuration
```

## 🔧 Useful Commands

### Create a superuser
```bash
python manage.py createsuperuser
```

### Apply migrations
```bash
python manage.py migrate
```

### Create new migrations
```bash
python manage.py makemigrations
```

### Collect static files
```bash
python manage.py collectstatic
```

### Access Django shell
```bash
python manage.py shell
```

## 📞 Support

For any questions or issues, contact the technical team.

## 📄 License

Proprietary - Shine Congo

---

**Version:** 1.0.0  
**Last updated:** 2025

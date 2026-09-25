# EcoHub Electronics

EcoHub is a Django-based electronics inventory and sales management system. It provides a single workspace for managing products, stock movements, customers, quotations, invoices, receipts, users, and operational reports.

## Features

- Product and category management
- Stock-in and stock movement history
- Customer records and account numbers
- Quotations, invoices, and receipts
- Printable sales documents and reports
- Custom user authentication and administration
- MySQL database support

## Technology

- Python 3.10+
- Django 4.2+
- MySQL 8+
- `mysqlclient` database driver
- `openpyxl` for inventory spreadsheet uploads
- `python-dotenv` for environment configuration
- Gunicorn and Nginx for production deployment

## Local Setup

### 1. Clone the repository

```bash
git clone git@github.com:mosesmuriiki2/EcoHub-Electronics-.git
cd EcoHub-Electronics-
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install Django mysqlclient openpyxl python-dotenv gunicorn
```

On Ubuntu/Debian, `mysqlclient` may require system packages first:

```bash
sudo apt update
sudo apt install -y python3-dev default-libmysqlclient-dev build-essential pkg-config
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with values for the local database. Never commit `.env` or production secrets.

```dotenv
DEBUG=True
SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=ecohub
DB_USER=ecohub_user
DB_PASSWORD=replace-with-a-database-password
DB_HOST=127.0.0.1
DB_PORT=3306
```

### 4. Create the MySQL database

```sql
CREATE DATABASE ecohub CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ecohub_user'@'localhost' IDENTIFIED BY 'replace-with-a-database-password';
GRANT ALL PRIVILEGES ON ecohub.* TO 'ecohub_user'@'localhost';
FLUSH PRIVILEGES;
```

### 5. Apply migrations and create an administrator

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

### 6. Run the development server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. The Django admin is available at `/admin/`.

## Production Deployment

The following example targets an Ubuntu server with the application checked out at `/srv/ecohub`.

### 1. Install server dependencies

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev default-libmysqlclient-dev build-essential pkg-config nginx
```

Create the virtual environment and install the application dependencies:

```bash
cd /srv/ecohub
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install Django mysqlclient openpyxl python-dotenv gunicorn
```

### 2. Configure production settings

Create `/srv/ecohub/.env` and use production values:

```dotenv
DEBUG=False
SECRET_KEY=generate-a-unique-long-random-value
ALLOWED_HOSTS=example.com,www.example.com

DB_NAME=ecohub
DB_USER=ecohub_user
DB_PASSWORD=use-a-strong-unique-password
DB_HOST=127.0.0.1
DB_PORT=3306
```

Keep the file readable only by the deployment user:

```bash
chmod 600 /srv/ecohub/.env
```

Before going live, confirm that the production database exists and that the database user has only the permissions required by the application.

### 3. Prepare the application

```bash
cd /srv/ecohub
source venv/bin/activate
python manage.py check --deploy
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

`collectstatic` places static assets in `staticfiles/`. User uploads are stored in `media/`; make sure this directory is persistent and backed up.

### 4. Create a systemd service for Gunicorn

Create `/etc/systemd/system/ecohub.service`:

```ini
[Unit]
Description=EcoHub Gunicorn service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/ecohub
EnvironmentFile=/srv/ecohub/.env
ExecStart=/srv/ecohub/venv/bin/gunicorn --workers 3 --bind unix:/run/ecohub.sock config.wsgi:application
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Start and enable the service:

```bash
sudo chown -R www-data:www-data /srv/ecohub
sudo systemctl daemon-reload
sudo systemctl enable --now ecohub
sudo systemctl status ecohub
```

### 5. Configure Nginx

Create `/etc/nginx/sites-available/ecohub`:

```nginx
server {
	listen 80;
	server_name example.com www.example.com;

	client_max_body_size 20M;

	location /static/ {
		alias /srv/ecohub/staticfiles/;
	}

	location /media/ {
		alias /srv/ecohub/media/;
	}

	location / {
		include proxy_params;
		proxy_pass http://unix:/run/ecohub.sock;
	}
}
```

Enable the site and validate the configuration:

```bash
sudo ln -s /etc/nginx/sites-available/ecohub /etc/nginx/sites-enabled/ecohub
sudo nginx -t
sudo systemctl reload nginx
```

Add HTTPS before exposing the application publicly. For example, Certbot can provision a certificate for an Nginx site:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d www.example.com
```

## Deployment Checklist

- Set `DEBUG=False` and use a unique `SECRET_KEY`.
- Set `ALLOWED_HOSTS` to the real domain names.
- Run `python manage.py check --deploy`.
- Run migrations before restarting the application.
- Run `collectstatic` after static asset changes.
- Configure HTTPS and secure database credentials.
- Back up the MySQL database and the `media/` directory.
- Review Gunicorn and Nginx logs with `journalctl` and `/var/log/nginx/`.

## Useful Commands

```bash
python manage.py test
python manage.py makemigrations
python manage.py migrate
python manage.py shell
```

## Project Structure

| Path | Purpose |
| --- | --- |
| `config/` | Django settings, URLs, and WSGI configuration |
| `accounts/` | Authentication and user management |
| `inventory/` | Products, categories, stock, and movements |
| `customers/` | Customer records |
| `sales/` | Quotations, invoices, receipts, and sales documents |
| `reports/` | Reporting views |
| `templates/` | HTML templates |
| `static/` | Source static assets |
| `staticfiles/` | Collected static assets for deployment |
| `media/` | User-uploaded files |

## License

No license has been specified yet.

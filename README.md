# EcoHub Electronics

EcoHub is a Django-based electronics inventory and sales management system. It provides a single workspace for managing products, stock movements, customers, quotations, invoices, receipts, users, and operational reports.

## Features

- Product and category management
- Stock-in and stock movement history
- Customer records and account numbers
- Quotations, invoices, and receipts
- Printable sales documents and reports
- Custom user authentication and administration
- PostgreSQL database support through Supabase

## Technology

- Python 3.10+
- Django 5.0+
- PostgreSQL (Supabase)
- `psycopg` PostgreSQL database driver
- `openpyxl` for inventory spreadsheet uploads
- `python-dotenv` for environment configuration
- Gunicorn and Nginx for production deployment

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/musatechnologieske-bit-23/ecohub-electronics.git
cd ecohub-electronics
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Ubuntu/Debian, install WeasyPrint's system libraries before installing Python packages:

```bash
sudo apt update
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libjpeg-dev libopenjp2-7
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and replace the secret placeholder. By default, local development
uses SQLite. To use Supabase locally, set `DATABASE_URL` to the PostgreSQL
connection string from your Supabase project. Never commit `.env` or production
secrets.

```dotenv
DEBUG=True
SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=
```

### 4. Apply migrations and create an administrator

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
```

### 5. Run the development server

```bash
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. The Django admin is available at `/admin/`.

## Production Deployment

### Vercel and Supabase (free-tier setup)

1. Create a Supabase project and copy its PostgreSQL connection string from
   **Project Settings → Database → Connect**. For Vercel, use the Supabase
   **Session pooler** connection string if the direct database host is not
   reachable from your deployment.
2. Import this GitHub repository into Vercel. Vercel detects the Django
   project, builds its Python function, and collects static files.
3. Add these environment variables to the Vercel project for Production and
   Preview as needed:

   | Variable | Value |
   | --- | --- |
   | `DEBUG` | `False` |
   | `SECRET_KEY` | A newly generated, private Django secret |
   | `DATABASE_URL` | The Supabase PostgreSQL connection string |
   | `ALLOWED_HOSTS` | Optional comma-separated custom domains |
   | `CSRF_TRUSTED_ORIGINS` | Optional full origins for custom domains, e.g. `https://example.com` |

   Vercel sets the deployment, branch, and production URL variables
   automatically; the app trusts those hosts and their HTTPS origins. Add any
   custom domain to both `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
4. Deploy. Before using the app, link the project locally, pull its Production
   environment, and apply the schema migrations:

   ```bash
   vercel link
   vercel env pull .env.local --environment=production
   python manage.py migrate
   python manage.py createsuperuser
   ```

   The settings load `.env.local`, so these commands use the production
   database. Keep that file private; it is ignored by Git.
5. Visit the deployed site and sign in with the administrator you created.

Vercel's filesystem is temporary: uploaded files or other local writes are not
persistent. This app's existing MySQL data is also not copied to Supabase by
changing the connection string; export and import existing records separately
if you need to keep them. Supabase and Vercel free-tier quotas and availability
limits apply.

WeasyPrint PDF generation depends on native Pango libraries. The import is
deferred until a PDF is requested so that a missing native library does not
prevent the rest of the Django app from starting; verify PDF exports on Vercel
before relying on them.

### Ubuntu server deployment

The following example targets an Ubuntu server with the application checked out at `/srv/ecohub`.

### 1. Install server dependencies

```bash
sudo apt update
sudo apt install -y python3-venv nginx libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libjpeg-dev libopenjp2-7
```

Create the virtual environment and install the application dependencies:

```bash
cd /srv/ecohub
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Configure production settings

Create `/srv/ecohub/.env` and use production values:

```dotenv
DEBUG=False
SECRET_KEY=generate-a-unique-long-random-value
ALLOWED_HOSTS=example.com,www.example.com

DATABASE_URL=postgresql://user:password@host:5432/database?sslmode=require
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
- Back up the PostgreSQL database and the `media/` directory.
- Review Gunicorn and Nginx logs with `journalctl` and `/var/log/nginx/`.

## Railway Deployment

The repository includes `railway.json` and `.python-version`. Railway detects
the Python app from `requirements.txt`, installs the dependencies, collects
static files, runs database migrations, and starts Gunicorn. The `/health/`
endpoint is used for Railway's deployment health check.

1. Create a Railway project from this GitHub repository. Use Supabase
   PostgreSQL, or attach a PostgreSQL service.
2. Set the web service's `SECRET_KEY` to a unique random value and `DEBUG` to
	`False`. Set `DATABASE_URL` to the PostgreSQL connection string.
3. Set `ALLOWED_HOSTS` to the Railway public domain and
	`CSRF_TRUSTED_ORIGINS` to its HTTPS origin.
4. Generate a public domain for the web service and deploy. Railway runs
	`collectstatic` and `migrate` at startup before Gunicorn serves the app.
5. Create the first administrator with a Railway one-off command:
	`python manage.py createsuperuser`.

Uploaded files are stored on the service filesystem by default and are not
persistent across deployments. Add a Railway volume or object storage before
relying on persistent user uploads.

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

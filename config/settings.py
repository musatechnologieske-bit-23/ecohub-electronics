"""
Django settings for Ecohub project.
"""

from pathlib import Path
from urllib.parse import urlparse
import os
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file (only present locally;
# on Railway, variables come from the platform directly and this is a no-op)
load_dotenv(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 't')
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-ecohub-local-development-only'
    else:
        raise ImproperlyConfigured('Set SECRET_KEY in the environment when DEBUG is False.')

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]
RAILWAY_PUBLIC_DOMAIN = os.getenv('RAILWAY_PUBLIC_DOMAIN')
if RAILWAY_PUBLIC_DOMAIN and RAILWAY_PUBLIC_DOMAIN not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]
if RAILWAY_PUBLIC_DOMAIN:
    railway_origin = f'https://{RAILWAY_PUBLIC_DOMAIN}'
    if railway_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(railway_origin)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Ecohub apps
    'accounts',
    'inventory',
    'customers',
    'sales',
    'reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
# Database
#
# On Railway, we read the single MYSQL_URL connection string that Railway
# auto-generates when a MySQL database is attached to this service
# (mysql://user:password@host:port/database). This avoids relying on
# individually-named DB_* reference variables, which are easy to mismatch
# against Railway's actual variable names.
#
# Locally (DEBUG=True), we fall back to DB_NAME / DB_USER / DB_PASSWORD /
# DB_HOST / DB_PORT from your .env file as before.
#
# In production (DEBUG=False), if neither MYSQL_URL nor a complete set of
# DB_* variables resolves to real values, we fail loudly here with a clear
# error instead of silently defaulting to 127.0.0.1/localhost and producing
# a confusing connection-refused error deep inside PyMySQL.
# ---------------------------------------------------------------------------

MYSQL_URL = os.getenv('MYSQL_URL', '').strip()

if MYSQL_URL:
    parsed = urlparse(MYSQL_URL)
    DB_NAME = parsed.path.lstrip('/')
    DB_USER = parsed.username or 'root'
    DB_PASSWORD = parsed.password or ''
    DB_HOST = parsed.hostname or ''
    DB_PORT = str(parsed.port or 3306)
else:
    DB_NAME = os.getenv('DB_NAME', '').strip()
    DB_USER = os.getenv('DB_USER', '').strip()
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_HOST = os.getenv('DB_HOST', '').strip()
    DB_PORT = os.getenv('DB_PORT', '').strip()

    if DEBUG:
        # Sensible local defaults so `runserver` works out of the box on a dev machine
        DB_NAME = DB_NAME or 'ecohub'
        DB_USER = DB_USER or 'root'
        DB_HOST = DB_HOST or '127.0.0.1'
        DB_PORT = DB_PORT or '3306'

if not DEBUG:
    missing = [
        name for name, value in [
            ('DB_NAME', DB_NAME),
            ('DB_USER', DB_USER),
            ('DB_HOST', DB_HOST),
            ('DB_PORT', DB_PORT),
        ] if not value
    ]
    if missing:
        raise ImproperlyConfigured(
            f"Missing or empty required database settings: {', '.join(missing)}. "
            "Ensure MYSQL_URL (or DB_NAME/DB_USER/DB_HOST/DB_PORT) is set on the Railway service."
        )

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
        'HOST': DB_HOST,
        'PORT': DB_PORT,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 3600 if not DEBUG else 0
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Authentication URLs
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
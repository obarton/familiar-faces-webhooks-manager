from pathlib import Path
import os
import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-key-change-in-prod')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'webhooks',
    'competitors',
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
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')
GOOGLE_SPREADSHEET_ID = os.environ.get('GOOGLE_SPREADSHEET_ID', '1TnOUIheEznDDl6AV7WoI2gcoRsExCvjGo10MX9Zf58E')

MAILCHIMP_API_KEY = os.environ.get('MAILCHIMP_API_KEY', '')
MAILCHIMP_AUDIENCE_ID = os.environ.get('MAILCHIMP_AUDIENCE_ID', '')

# Firecrawl (competitor content tracker). Unset = feature degrades gracefully.
FIRECRAWL_API_KEY = os.environ.get('FIRECRAWL_API_KEY', '')

# Apify (Instagram / TikTok scraping — Firecrawl can't read those platforms).
# Unset = IG/TikTok channels are skipped with a UI hint, rest still works.
APIFY_API_TOKEN = os.environ.get('APIFY_API_TOKEN', '')
APIFY_INSTAGRAM_ACTOR = os.environ.get('APIFY_INSTAGRAM_ACTOR', 'apify/instagram-scraper')
APIFY_TIKTOK_ACTOR = os.environ.get('APIFY_TIKTOK_ACTOR', 'clockworks/tiktok-scraper')

# One-time deep pull the first time a competitor is refreshed; recurring
# refreshes then use the per-competitor crawl_limit.
COMPETITOR_BACKFILL_LIMIT = int(os.environ.get('COMPETITOR_BACKFILL_LIMIT', '200'))

# Anthropic / Claude — AI competitor summaries. Unset = the summary section
# shows a hint instead of generating.
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
COMPETITOR_AI_MODEL = os.environ.get('COMPETITOR_AI_MODEL', 'claude-opus-4-8')

# Your brand, used to relate competitors back to you in AI summaries.
BRAND_NAME = os.environ.get('BRAND_NAME', 'Familiar Faces')
# Optional owner name — personalizes the landscape report's TL;DR ("TL;DR for X").
BRAND_OWNER = os.environ.get('BRAND_OWNER', '')
BRAND_DESCRIPTION = os.environ.get(
    'BRAND_DESCRIPTION',
    'Familiar Faces is a live-events and nightlife brand that produces recurring '
    'social events and parties across multiple U.S. cities (LA, Bay Area, NYC, and '
    'more), building community around music, culture, and in-person gatherings.',
)

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Logging
# With DEBUG=False and no LOGGING config, unhandled 500 tracebacks are not
# written anywhere you can see. Send everything to the console (captured by the
# app server / container logs) so request errors are diagnosable in production.
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        # Ensure unhandled request exceptions (500s) log full tracebacks.
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'webhooks': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}

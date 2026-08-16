"""Settings for the OpenKinetics Data Django application."""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR / "backend"

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "dev-only-openkinetics-data-secret-key-change-in-production",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,data.openkinetics.org",
    ).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "data_api",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "openkinetics_data.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BACKEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "openkinetics_data.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

if os.environ.get("POSTGRES_DB"):
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ.get("POSTGRES_USER", "openkinetics"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BACKEND_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BACKEND_DIR / "media"

RELEASES_ROOT = Path(os.environ.get("OPENKINETICS_RELEASES_ROOT", str(BASE_DIR / "releases")))
RELEASES_URL_BASE = os.environ.get("OPENKINETICS_RELEASES_URL_BASE", "/releases")
SEQUENCE_INFO_ROOT = Path(
    os.environ.get(
        "OPENKINETICS_SEQUENCE_INFO_ROOT",
        str(BASE_DIR / "mounted_sequence_info"),
    )
)
SEQUENCE_ARTIFACTS_URL_BASE = os.environ.get(
    "OPENKINETICS_SEQUENCE_ARTIFACTS_URL_BASE",
    "/sequence-artifacts",
)

SEQUENCE_ARTIFACT_ROOTS = {
    "esm2_residue": os.environ.get("OPENKINETICS_ESM2_RESIDUE_ROOT", "esm2_layer_26/residue_vecs"),
    "esmc_residue": os.environ.get("OPENKINETICS_ESMC_RESIDUE_ROOT", "esmc_layer_32/residue_vecs"),
    "prot_t5_residue": os.environ.get(
        "OPENKINETICS_PROT_T5_RESIDUE_ROOT",
        "prot_t5_layer_19/residue_vecs",
    ),
    "pseq2sites_scores": os.environ.get("OPENKINETICS_PSEQ2SITES_ROOT", "pseq2sites_scores"),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CSRF_TRUSTED_ORIGINS",
        "https://data.openkinetics.org",
    ).split(",")
    if origin.strip()
]

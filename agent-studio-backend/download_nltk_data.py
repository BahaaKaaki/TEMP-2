"""Pre-download NLP models needed by the unstructured library.

Downloads NLTK data and the spaCy model at build time so the container
doesn't need outbound network access at runtime.

Usage: python3 download_nltk_data.py <nltk_base_dir>
"""
import os
import urllib.request
import zipfile
import io
import ssl
import time
import sys
from urllib.parse import urlparse

ctx = ssl.create_default_context()
MAX_RETRIES = 5
RETRY_DELAY = 10

_ALLOWED_HOSTS = frozenset({
    "raw.githubusercontent.com",
    "github.com",
})

nltk_base = sys.argv[1] if len(sys.argv) > 1 else "/usr/local/share/nltk_data"


def _validate_url(url: str) -> None:
    """Ensure URL targets an allowed host (SSRF prevention)."""
    parsed = urlparse(url)
    if parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError(f"URL host not in allow-list: {parsed.hostname}")


def _safe_path(base: str, target: str) -> str:
    """Resolve *target* under *base* and ensure it stays within it."""
    real_base = os.path.realpath(base)
    real_target = os.path.realpath(os.path.join(real_base, target))
    if not real_target.startswith(real_base + os.sep) and real_target != real_base:
        raise ValueError(f"Path traversal blocked: {target}")
    return real_target


def download_with_retries(url, description):
    """Download a URL with retries, returning the bytes."""
    _validate_url(url)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"Downloading {description} (attempt {attempt}/{MAX_RETRIES})...")
            data = urllib.request.urlopen(url, context=ctx, timeout=60).read()
            print(f"Downloaded {len(data)} bytes")
            return data
        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            if attempt == MAX_RETRIES:
                print(f"FATAL: Could not download {description} after {MAX_RETRIES} attempts")
                sys.exit(1)
            time.sleep(RETRY_DELAY)


# --- NLTK data ---
nltk_packages = [
    ("tokenizers/punkt_tab", "tokenizers"),
    ("taggers/averaged_perceptron_tagger_eng", "taggers"),
]

for pkg, subdir in nltk_packages:
    dest = _safe_path(nltk_base, subdir)
    os.makedirs(dest, exist_ok=True)
    url = f"https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/{pkg}.zip"
    data = download_with_retries(url, pkg)
    zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
    print(f"Extracted {pkg} to {dest}")

print("NLTK data downloaded successfully")

# --- spaCy model (needed by unstructured for sentence tokenization) ---
SPACY_URL = "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
SPACY_WHL = "/tmp/en_core_web_sm-3.8.0-py3-none-any.whl"

data = download_with_retries(SPACY_URL, "spaCy en_core_web_sm-3.8.0")
with open(SPACY_WHL, "wb") as f:
    f.write(data)
print(f"spaCy model saved to {SPACY_WHL}")

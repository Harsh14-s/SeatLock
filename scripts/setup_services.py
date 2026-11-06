import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / ".bin"
PG_DIR = BIN_DIR / "pgsql"
PG_DATA = PG_DIR / "data"
REDIS_DIR = BIN_DIR / "redis"

BIN_DIR.mkdir(parents=True, exist_ok=True)


def download_file(url: str, dest: Path):
    print(f"Downloading {url} to {dest.name}...")
    urllib.request.urlretrieve(url, str(dest))
    print(f"Downloaded {dest.name} ({dest.stat().st_size / (1024*1024):.1f} MB).")


def setup_postgres():
    bki_file = PG_DIR / "share" / "postgres.bki"
    if not bki_file.exists():
        pg_zip = BIN_DIR / "pgsql.zip"
        if not pg_zip.exists():
            pg_url = "https://get.enterprisedb.com/postgresql/postgresql-16.3-1-windows-x64-binaries.zip"
            download_file(pg_url, pg_zip)

        print("Extracting PostgreSQL archive...")
        with zipfile.ZipFile(pg_zip, "r") as zf:
            zf.extractall(BIN_DIR)
        print("Extracted PostgreSQL.")
        if pg_zip.exists():
            os.remove(pg_zip)

    # Initialize data directory
    pg_bin = PG_DIR / "bin"
    if not (PG_DATA / "PG_VERSION").exists():
        print("Initializing PostgreSQL database cluster...")
        if PG_DATA.exists():
            shutil.rmtree(PG_DATA)
        initdb_exe = str(pg_bin / "initdb.exe")
        cmd = [
            initdb_exe,
            "-D", str(PG_DATA),
            "-U", "postgres",
            "-A", "trust",
            "--encoding=UTF8",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"initdb error: {res.stderr}")
            sys.exit(1)
        print("PostgreSQL cluster initialized.")
    else:
        print("PostgreSQL cluster already initialized.")


def setup_redis():
    if not (REDIS_DIR / "redis-server.exe").exists():
        REDIS_DIR.mkdir(parents=True, exist_ok=True)
        redis_zip = BIN_DIR / "redis.zip"
        redis_url = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
        download_file(redis_url, redis_zip)

        print("Extracting Redis...")
        with zipfile.ZipFile(redis_zip, "r") as zf:
            zf.extractall(REDIS_DIR)
        if redis_zip.exists():
            os.remove(redis_zip)
        print("Redis setup complete.")
    else:
        print("Redis already present.")


if __name__ == "__main__":
    setup_postgres()
    setup_redis()
    print("\nSUCCESS: All services ready in .bin/")

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / ".bin"
PG_BIN = BIN_DIR / "pgsql" / "bin"
PG_DATA = BIN_DIR / "pgsql" / "data"
REDIS_DIR = BIN_DIR / "redis"


def is_pg_ready():
    pg_isready = str(PG_BIN / "pg_isready.exe")
    res = subprocess.run([pg_isready, "-h", "127.0.0.1", "-p", "5432"], capture_output=True)
    return res.returncode == 0


def start_services():
    DETACHED_FLAGS = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
    ) if os.name == "nt" else 0

    if not is_pg_ready():
        print("Starting PostgreSQL...")
        pg_exe = str(PG_BIN / "postgres.exe")
        log_file = open(PG_DATA / "pg_server.log", "a")
        subprocess.Popen(
            [pg_exe, "-D", str(PG_DATA), "-p", "5432"],
            stdout=log_file,
            stderr=log_file,
            creationflags=DETACHED_FLAGS,
        )

        # Wait for PostgreSQL to become ready
        for _ in range(30):
            time.sleep(1)
            if is_pg_ready():
                print("PostgreSQL is ready!")
                break
        else:
            print("PostgreSQL did not start in time. Check pg_server.log.")
            sys.exit(1)
    else:
        print("PostgreSQL is already running.")

    # Ensure seatlock database exists
    psql_exe = str(PG_BIN / "psql.exe")
    check_cmd = [
        psql_exe, "-h", "127.0.0.1", "-U", "postgres", "-p", "5432",
        "-t", "-A", "-c", "SELECT 1 FROM pg_database WHERE datname='seatlock'"
    ]
    res = subprocess.run(check_cmd, capture_output=True, text=True)
    if "1" not in res.stdout:
        print("Creating 'seatlock' database...")
        createdb_exe = str(PG_BIN / "createdb.exe")
        subprocess.run([createdb_exe, "-h", "127.0.0.1", "-U", "postgres", "-p", "5432", "seatlock"], check=False)

    # Check Redis
    redis_cli = str(REDIS_DIR / "redis-cli.exe")
    r_check = subprocess.run([redis_cli, "-h", "127.0.0.1", "-p", "6379", "ping"], capture_output=True, text=True)
    if "PONG" not in r_check.stdout:
        print("Starting Redis...")
        redis_exe = str(REDIS_DIR / "redis-server.exe")
        redis_log = open(REDIS_DIR / "redis_server.log", "a")
        subprocess.Popen(
            [redis_exe, "--port", "6379"],
            stdout=redis_log,
            stderr=redis_log,
            creationflags=DETACHED_FLAGS,
        )
        time.sleep(1)
        print("Redis started!")
    else:
        print("Redis is already running.")

    print("\nSUCCESS: All services are active and ready on ports 5432 and 6379.")


def stop_services():
    print("Stopping PostgreSQL and Redis...")
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "postgres.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "redis-server.exe"], capture_output=True)
    print("Services stopped.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop_services()
    else:
        start_services()

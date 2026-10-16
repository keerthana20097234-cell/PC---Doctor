import os
import platform
import socket
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

try:
    import psutil
except ImportError:
    psutil = None


APP_DIR = Path(__file__).resolve().parent
configured_database = os.environ.get("PCDOCTOR_DB_PATH") or os.environ.get("GHOSTFIX_DB_PATH")
default_database = APP_DIR / "pcdoctor.db"
legacy_database = APP_DIR / "ghostfix.db"
if not configured_database and not default_database.exists() and legacy_database.exists():
    default_database = legacy_database
DATABASE_PATH = Path(configured_database) if configured_database else default_database
COMPUTER_ID = platform.node() or "local-computer"
MODEL = "gemma3:1b"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
app = FastAPI(title="PC Doctor", version="1.0.0")


class ProblemRequest(BaseModel):
    problem: str = Field(min_length=1, max_length=2000)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(database()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                computer_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL,
                dedup_key TEXT
            )
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(issues)")}
        if "dedup_key" not in columns:
            connection.execute("ALTER TABLE issues ADD COLUMN dedup_key TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_issues_filters ON issues(computer_id, created_at, severity)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_issues_dedupe ON issues(computer_id, dedup_key, created_at)"
        )
        connection.commit()


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def save_issue(
    kind: str,
    severity: str,
    title: str,
    details: str,
    deduplicate: bool = False,
    dedup_key: Optional[str] = None,
) -> None:
    timestamp = utc_now().isoformat()
    with closing(database()) as connection:
        if deduplicate:
            if dedup_key:
                recent = connection.execute(
                    """
                    SELECT 1 FROM issues
                    WHERE computer_id = ? AND kind = ? AND dedup_key = ? AND created_at >= ?
                    LIMIT 1
                    """,
                    (COMPUTER_ID, kind, dedup_key, (utc_now() - timedelta(minutes=5)).isoformat()),
                ).fetchone()
            else:
                recent = connection.execute(
                    """
                    SELECT 1 FROM issues
                    WHERE computer_id = ? AND kind = ? AND title = ? AND created_at >= ?
                    LIMIT 1
                    """,
                    (COMPUTER_ID, kind, title, (utc_now() - timedelta(minutes=5)).isoformat()),
                ).fetchone()
            if recent:
                return
        connection.execute(
            """
            INSERT INTO issues (computer_id, kind, severity, title, details, created_at, dedup_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (COMPUTER_ID, kind, severity, title, details, timestamp, dedup_key),
        )
        connection.commit()


def internet_status() -> tuple[str, Optional[str]]:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
            return "Reachable", None
    except OSError:
        return "No response / offline", "Internet check did not respond; local network restrictions may affect this check."


def collect_health() -> dict:
    now = utc_now().isoformat()
    info = {
        "computer_id": COMPUTER_ID,
        "computer": COMPUTER_ID,
        "monitoring": "live" if psutil is not None else "unavailable",
        "status": "unavailable" if psutil is None else "green",
        "cpu": None,
        "ram": None,
        "disk_used_percent": None,
        "disk_free_gb": None,
        "disk_total_gb": None,
        "network": "Checking",
        "alerts": [],
        "last_updated": now,
    }

    if psutil is None:
        info["alerts"].append("System metrics are unavailable. Install the requirements to enable monitoring.")
    else:
        try:
            info["cpu"] = round(psutil.cpu_percent(interval=0.25), 1)
            memory = psutil.virtual_memory()
            info["ram"] = round(memory.percent, 1)
            drive = os.environ.get("SystemDrive", "C:") if os.name == "nt" else "/"
            disk = psutil.disk_usage(drive + "\\" if os.name == "nt" else drive)
            info["disk_used_percent"] = round(disk.percent, 1)
            info["disk_free_gb"] = round(disk.free / (1024**3), 1)
            info["disk_total_gb"] = round(disk.total / (1024**3), 1)
        except (OSError, RuntimeError) as error:
            info["monitoring"] = "partial"
            info["status"] = "yellow"
            info["alerts"].append(f"Some system metrics could not be read: {error}")

        cpu = info["cpu"]
        ram = info["ram"]
        disk_used = info["disk_used_percent"]
        if cpu is not None and cpu >= 95:
            info["status"] = "red"
            info["alerts"].append(f"CPU usage is critically high ({cpu}%).")
        if ram is not None and ram >= 95:
            info["status"] = "red"
            info["alerts"].append(f"RAM usage is critically high ({ram}%).")
        if disk_used is not None and disk_used >= 97:
            info["status"] = "red"
            info["alerts"].append(f"Disk is critically full ({disk_used}% used).")

        if cpu is not None and 80 <= cpu < 95:
            if info["status"] != "red":
                info["status"] = "yellow"
            info["alerts"].append(f"CPU usage is high ({cpu}%).")
        if ram is not None and 80 <= ram < 95:
            if info["status"] != "red":
                info["status"] = "yellow"
            info["alerts"].append(f"RAM usage is high ({ram}%).")
        if disk_used is not None and 90 <= disk_used < 97:
            if info["status"] != "red":
                info["status"] = "yellow"
            info["alerts"].append(f"Disk space is running low ({disk_used}% used).")

    info["network"], network_warning = internet_status()
    if network_warning:
        info["alerts"].append(network_warning)
        if info["status"] == "green":
            info["status"] = "yellow"

    for alert in info["alerts"]:
        severity = "critical" if "critically" in alert else "warning"
        resource = (
            "cpu" if alert.startswith("CPU ")
            else "ram" if alert.startswith("RAM ")
            else "disk" if alert.startswith("Disk ")
            else "network"
        )
        save_issue(
            "alert",
            severity,
            alert,
            "Detected by the local computer health check.",
            deduplicate=True,
            dedup_key=f"{resource}:{severity}",
        )
    return info


def issue_filters(
    computer_id: Optional[str], start_date: Optional[str], end_date: Optional[str], severity: Optional[str]
) -> tuple[str, list[str]]:
    clauses: list[str] = []
    values: list[str] = []
    if computer_id:
        clauses.append("computer_id = ?")
        values.append(computer_id)
    if start_date:
        clauses.append("created_at >= ?")
        values.append(f"{start_date}T00:00:00+00:00")
    if end_date:
        clauses.append("created_at < ?")
        values.append(f"{end_date}T23:59:59.999999+00:00")
    if severity:
        clauses.append("severity = ?")
        values.append(severity.lower())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, values


@app.get("/")
def home():
    return FileResponse(APP_DIR / "index.html")


@app.get("/health")
@app.get("/api/health")
def health():
    return collect_health()


@app.get("/api/computers")
def computers():
    health_info = collect_health()
    return {
        "computers": [
            {
                **health_info,
                "name": COMPUTER_ID,
                "kind": "this computer",
            }
        ],
        "remote_monitoring": {
            "configured": False,
            "message": "No remote agents are registered. Only this computer is monitored live.",
        },
    }


@app.post("/analyze")
@app.post("/api/analyze")
def analyze(data: ProblemRequest):
    problem = data.problem.strip()
    if not problem:
        return {"answer": "Please describe the computer problem first.", "ai_available": False}

    prompt = f"""You are PC Doctor, a college computer lab troubleshooting assistant.
Explain in simple English using these headings:
1. Problem summary (restate only what the user reported)
2. Possible causes (possibilities, not confirmed diagnoses)
3. Safe step-by-step solutions
4. Prevention
5. Safety precautions and when to contact the lab technician
The application displays the user's exact description separately as the detected fact. Do not invent or imply other observed symptoms, measurements, or context. Do not add a separate detected-facts section. Keep every cause clearly uncertain.
Do not advise opening hardware, changing electrical connections, deleting important files, or bypassing security.
Problem: {problem}"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False, "options": {"num_predict": 384}},
            timeout=(3, 90),
        )
        response.raise_for_status()
        payload = response.json()
        answer_value = payload.get("response", "") if isinstance(payload, dict) else ""
        answer = answer_value.strip() if isinstance(answer_value, str) else ""
        if not answer:
            answer = "Ollama returned an empty response. Please try again."
            ai_available = False
        else:
            answer = (
                f"Detected fact (from your description):\n- {problem}\n\n"
                f"AI guidance (possible causes, not a confirmed diagnosis):\n{answer}"
            )
            ai_available = True
    except requests.exceptions.ConnectionError:
        answer = f"Cannot connect to local Ollama. Start Ollama and make sure {MODEL} is downloaded."
        ai_available = False
    except requests.exceptions.Timeout:
        answer = "The AI took too long to respond. Try again or contact the lab technician."
        ai_available = False
    except (requests.exceptions.RequestException, ValueError):
        answer = "Ollama could not complete the request. Check that the local service is running and the model is available."
        ai_available = False

    save_issue("troubleshooting", "info", problem, answer)
    return {"answer": answer, "ai_available": ai_available, "model": MODEL if ai_available else None}


@app.get("/api/issues")
def issues(
    computer_id: Optional[str] = None,
    start_date: Optional[str] = Query(default=None, alias="from"),
    end_date: Optional[str] = Query(default=None, alias="to"),
    severity: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    where, values = issue_filters(computer_id, start_date, end_date, severity)
    with closing(database()) as connection:
        rows = connection.execute(
            f"SELECT id, computer_id, kind, severity, title, details, created_at FROM issues {where} ORDER BY id DESC LIMIT ?",
            (*values, limit),
        ).fetchall()
    return {"issues": [dict(row) for row in rows]}


@app.get("/api/reports/latest", response_class=PlainTextResponse)
def latest_report():
    health_info = collect_health()
    with closing(database()) as connection:
        rows = connection.execute(
            "SELECT created_at, kind, severity, title, details FROM issues ORDER BY id DESC LIMIT 25"
        ).fetchall()
    report = [
        "PC DOCTOR - TECHNICIAN REPORT",
        f"Generated: {utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Computer: {COMPUTER_ID}",
        "Monitoring: This computer only (live)" if health_info["monitoring"] == "live" else "Monitoring: unavailable",
        f"Health status: {health_info['status'].upper()}",
        f"CPU: {health_info['cpu']}%",
        f"RAM: {health_info['ram']}%",
        f"Disk used: {health_info['disk_used_percent']}% ({health_info['disk_free_gb']} GB free)",
        f"Network: {health_info['network']}",
        "",
        "RECENT ISSUES",
    ]
    for row in rows:
        report.extend(
            [
                f"[{row['created_at']}] {row['severity'].upper()} / {row['kind']}: {row['title']}",
                row["details"],
                "",
            ]
        )
    return PlainTextResponse(
        "\n".join(report),
        headers={"Content-Disposition": 'attachment; filename="PC-Doctor-Technician-Report.txt"'},
    )

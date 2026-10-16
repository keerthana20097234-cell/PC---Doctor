# PC Doctor

PC Doctor is a local-first prototype for monitoring a college lab computer, recording health alerts and troubleshooting requests, and giving technicians a clear dashboard. It monitors the computer running the service; it does not pretend that other lab computers are online.

## Features

- Live CPU, RAM, system-drive usage/free space, and internet reachability checks, refreshed every 10 seconds.
- Green, yellow, and red health states with the threshold warning that caused them.
- Responsive dashboard with a session-only CPU/RAM trend, computer health map, recent issue history, filters, and a downloadable technician report.
- Local Ollama troubleshooting with `gemma3:1b` when available. Responses are prompted to separate facts provided by the user from possible causes, and to provide steps, prevention, and safety guidance.
- SQLite persistence for threshold alerts and troubleshooting records.
- Explicit remote-agent status. No remote computers are displayed unless real agent registration/communication is implemented.

## Requirements

- Python 3.10 or newer (Python 3.11/3.12 are recommended).
- Windows, macOS, or Linux.
- Ollama is optional; monitoring and history work without it.

## Install and run

Open a terminal in the `GhostFix-AI` project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Keep the terminal open while using the dashboard. The server binds to loopback (`127.0.0.1`) by default; do not change that for an untrusted network.
Do not open `index.html` directly from File Explorer: the dashboard's monitoring, issue history, and AI Doctor require the FastAPI server.

Optional AI setup:

```powershell
ollama pull gemma3:1b
ollama serve
```

If Ollama is not installed/running or the model is missing, the app reports that AI is unavailable. It does not claim that an AI diagnosis was produced.

For Command Prompt, activate the virtual environment with:

```bat
.venv\Scripts\activate.bat
```

## API overview

- `GET /api/health` — current local machine health.
- `GET /api/computers` — live local computer and remote-agent configuration state.
- `POST /api/analyze` — local Ollama troubleshooting; request JSON: `{"problem":"..."}` (maximum 2,000 characters).
- `GET /api/issues` — issue history; optional `computer_id`, `from`, `to`, and `severity` filters.
- `GET /api/reports/latest` — download a text technician report.

The older `GET /health` and `POST /analyze` routes remain available for compatibility.

## Data, privacy, and limitations

- `pcdoctor.db` is created in the project directory by default. An existing `ghostfix.db` is reused if present, preserving earlier issue history. Set `PCDOCTOR_DB_PATH` to choose another SQLite path (`GHOSTFIX_DB_PATH` remains supported for compatibility). Keep this local database private; it contains user-entered troubleshooting descriptions and local alerts.
- Troubleshooting prompts are sent to the Ollama service at `127.0.0.1:11434` only. No third-party AI service is used by this prototype.
- The internet test makes a short TCP connectivity check to `1.1.1.1:53`; campus firewall rules may cause a false offline warning.
- Resource thresholds are simple current-state warnings, not diagnoses or failure predictions. Trend samples are kept in browser memory for the current page session and are not historical telemetry.
- Remote monitoring of 50–100 computers is **not implemented**. This deployment only monitors its own computer. A real multi-computer system requires authenticated agents installed on each computer, TLS-protected ingestion, a shared server/database, enrollment and revocation, access control, and operational monitoring. Do not expose this prototype's API to a public or campus network.
- Notifications, multilingual/voice support, and predictive maintenance are future work. No future failure is predicted by this build.

## Project structure

- `app.py` — FastAPI API, local system monitoring, Ollama integration, SQLite persistence, and reports.
- `index.html` — responsive frontend with no external JavaScript dependencies.
- `requirements.txt` — Python dependencies.

## Troubleshooting

- **`psutil` or other import missing:** activate the virtual environment and rerun `python -m pip install -r requirements.txt`.
- **Port 8000 is occupied:** run `python -m uvicorn app:app --host 127.0.0.1 --port 8001` and open `http://127.0.0.1:8001`.
- **AI unavailable or slow:** start Ollama and run `ollama pull gemma3:1b`. Local inference may be slow on older hardware; requests time out after 90 seconds. Health monitoring does not depend on Ollama.
- **AI Doctor says the local server is required:** start Uvicorn from this project folder with `python -m uvicorn app:app --host 127.0.0.1 --port 8000`, then use <http://127.0.0.1:8000> instead of opening `index.html` directly.
- **Metrics unavailable:** check the terminal for local permission/system errors and confirm the virtual environment's dependencies are installed.

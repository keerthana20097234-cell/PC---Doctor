# PC Doctor - College Lab Health Monitor

An AI-powered system for live monitoring of college computer lab health.

## About
PC Doctor is a smart lab management solution that provides a complete overview of all PCs in a computer lab at a glance. It detects critical issues and finds instant solutions.

1. Live monitoring of PC health (CPU, RAM, Network)
2. Automatically detects critical problems
3. AI-powered diagnosis and suggests solutions
4. Tracks issue history for better lab management

## Features
- Your Lab, at a Glance Dashboard
- Real-time Status: Critical / Warning / Healthy
- AI Diagnostics & Fix Suggestions
- Issue History Log
- College Lab - Computer Health Monitoring

## Tech Stack
- Python
- Streamlit
- AI Diagnostics Module

## How to Run
```bash
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate

# Install dependencies
pip install -r requirements.txt
pip install streamlit

# Run the app
python -m streamlit run app.py --server.port 8775

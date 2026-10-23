# RecruitIQ — AI Recruitment Platform

RecruitIQ is a recruitment workflow prototype with a browser-based interface and a Flask API. It brings resume extraction, AI-assisted resume analysis, candidate tracking, screening notes, team-lead review, notifications, and pipeline visibility into one interface.

## Features

- Upload individual resumes in PDF, DOCX, or TXT format and extract text.
- Upload ZIP archives containing supported resume files for bulk text extraction.
- Request AI-assisted resume analysis through a configured provider: Anthropic Claude, OpenAI, Google Gemini (OpenAI-compatible endpoint), xAI Grok, or Groq.
- Track candidates, screening decisions, interview scores, notes, and call logs.
- Share candidate records for team-lead review and record decisions/comments.
- View pipeline status, summary statistics, notifications, and a health-check endpoint.
- Responsive dark/light interface styling.

## Project files

- `index.html` — browser UI.
- `app.py` — Flask API and local JSON-file storage.
- `requirements.txt` — Python dependencies.
- `.gitignore` — excludes local data files and environment artifacts.

## Requirements

- Python 3.10 or newer recommended.
- A modern browser.
- An API key for whichever AI provider you choose to use for AI analysis. Provider API usage may incur charges.

## Run locally

1. Clone or download this repository.
2. Create and activate a virtual environment:

   **Windows (PowerShell)**
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   **macOS/Linux**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   python -m pip install -r requirements.txt
   ```
4. Start the backend:
   ```bash
   python app.py
   ```
5. Open `index.html` in your browser. The UI expects the Flask API at `http://127.0.0.1:5000`.
6. Add your own provider API key through the application's provider/settings interface when using AI analysis.

The backend health check is available at `http://127.0.0.1:5000/health` while the server is running.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/extract-text` | Extract text from one uploaded file |
| `POST` | `/extract-zip` | Extract supported resumes from a ZIP archive |
| `POST` | `/analyze` | Send an analysis prompt to a selected AI provider |
| `GET/POST` | `/tracker` | List or add candidates |
| `GET/PATCH/DELETE` | `/tracker/<id>` | Read, update, or remove a candidate |
| `POST` | `/tracker/<id>/log` | Add a call/interview log entry |
| `GET` | `/tracker/stats` | Candidate pipeline and score summaries |
| `GET/POST` | `/shared` | List or share candidate records for TL review |
| `PATCH` | `/shared/<id>/decision` | Save a team-lead decision |
| `POST` | `/shared/<id>/comment` | Add a review comment |
| `GET/POST` | `/notifications` | Read or create notifications |
| `GET` | `/health` | Basic service and local record counts |

## Data storage and limitations

The backend creates `tracker_data.json`, `shared_candidates.json`, and `notifications.json` beside `app.py` as local storage files. These files are intentionally excluded from Git. Local JSON files are suitable for a prototype or single-user local setup, not concurrent or production use. Some team-lead UI state is stored in browser `localStorage` in the current frontend.

This repository is a prototype, not a production-ready recruitment service. Before deploying it for real users, add authentication and authorization, input/file size limits, request validation, secure server-side secret management, production-grade database storage, HTTPS, audit logging, and appropriate privacy controls. Do not upload real candidate resumes or personal data to a public repository.

## Privacy and API keys

- Never commit API keys, passwords, tokens, real resumes, or candidate records.
- Treat resumes and AI prompts as sensitive personal data. Only process them when you have a lawful basis and appropriate permission.
- The current frontend sends the selected provider API key to the local Flask backend in the analysis request. Use this only in a trusted local environment; for production, move provider credentials to server-side environment variables and never expose them to an untrusted browser.
- Review the code and provider terms before using it with confidential data.

## License

No license has been added yet. Add a license file if you want to specify how others may use, modify, or distribute this project.

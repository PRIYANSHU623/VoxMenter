# VoxMenter

VoxMenter is an AI-powered interview practice and English communication improvement application. It helps users practise interview questions, record answers, review transcripts, and receive AI-generated feedback.

## Features

- User registration and login with JWT authentication
- Interview practice sessions and question management
- Audio recording storage using Backblaze B2
- Speech transcription using faster-whisper
- AI-based answer evaluation using Gemini
- Feedback on clarity, grammar, technical correctness, and filler words
- Background processing using Celery and Redis
- Automated interview question discovery and generation

## Tech Stack

**Backend:** FastAPI, Python, SQLAlchemy

**Frontend:** React, Vite, TypeScript, Tailwind CSS

**Database:** SQLite (current development setup); PostgreSQL planned for deployment

**Audio Storage:** Backblaze B2

**Background Jobs:** Celery and Redis

**AI Services:** Gemini, faster-whisper

## Local Development

### Backend

1. Navigate to the backend directory.
2. Create and activate a Python virtual environment.
3. Install dependencies from `requirements.txt`.
4. Configure environment variables in a local `.env` file.
5. Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

API documentation: `http://127.0.0.1:8000/docs`

### Frontend

Navigate to `frontend/`, install dependencies using the package manager configured for the project, and start the Vite development server.

## Configuration

Use `backend/.env.example` as a reference for required environment variables. Never commit actual API keys, database credentials, JWT secrets, or Backblaze credentials.

## Testing

Run backend tests from the `backend/` directory using the project's configured test environment.

## Deployment

Deployment configuration and production database migration instructions will be added as hosting is configured.

## Project Status

VoxMenter is under active development. Features and deployment configuration may change.

# VoxMenter

VoxMenter is an AI-powered interview practice and communication coaching platform built to help users improve spoken English, interview confidence, and presentation quality.

It combines a FastAPI backend, a React + TypeScript frontend, and AI-powered evaluation services to create a full mock-interview workflow: users can practice questions, record their responses, review transcripts, and receive structured feedback on clarity, grammar, technical accuracy, and filler-word usage.

## Live demo

- Frontend: https://vox-menter.vercel.app

## Why VoxMenter?

Most interview preparation tools stop at question banks or generic practice. VoxMenter goes further by simulating a more realistic interview experience:

- users answer real interview questions in a guided flow
- audio responses are captured and stored securely
- transcripts are generated for review and analysis
- AI evaluates speaking quality and technical content
- progress can be tracked across multiple attempts

This makes it useful for job interview preparation, communication coaching, and performance improvement.

## Features

- JWT-based authentication and user session handling
- mock interview practice sessions and question workflows
- question management and dynamic question discovery
- per-question audio recording and playback
- speech-to-text transcription using Faster-Whisper
- AI-based answer evaluation using Gemini and related providers
- feedback on:
  - grammar and clarity
  - technical correctness
  - filler words and hesitation
  - spoken communication quality
- background processing with Celery and Redis
- cloud recording storage with Backblaze B2
- dashboard, history, review, and progress tracking pages

## Tech stack

### Backend
- Python 3.12
- FastAPI
- SQLAlchemy
- Pydantic
- PostgreSQL-ready configuration with SQLite for local development
- Celery + Redis
- Backblaze B2
- Faster-Whisper
- Google Generative AI / Gemini

### Frontend
- React 19
- TypeScript
- Vite
- Tailwind CSS
- React Router

## Architecture overview

```text
Frontend (React + Vite)
        |
        v
FastAPI backend
        |
        +--> Authentication and user APIs
        +--> Question and practice flow APIs
        +--> Recording and transcription APIs
        +--> AI evaluation and feedback services
        +--> Background task workers (Celery)
        |
        +--> SQLite / PostgreSQL database
        +--> Redis queue
        +--> Backblaze B2 object storage
```

## Project structure

```text
VoxMenter/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── tasks/
│   │   ├── main.py
│   │   └── celery_app.py
│   ├── tests/
│   ├── .env.example
│   ├── Dockerfile
│   ├── pytest.ini
│   ├── requirements.txt
│   └── scripts/
├── frontend/
│   ├── src/
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   └── index.html
├── README.md
├── .gitignore
└── LICENSE (if added later)
```

## Getting started

### Prerequisites

Before running the app locally, make sure you have:

- Python 3.12+
- Node.js 20+
- npm
- Redis running locally for Celery tasks
- FFmpeg installed
- API keys for:
  - Gemini or another AI provider
  - Backblaze B2
  - optional integrations such as OpenAI / Tavily

### 1) Clone the repository

```bash
git clone https://github.com/PRIYANSHU623/VoxMenter.git
cd VoxMenter
```

### 2) Set up the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Then update the values in `backend/.env` with your own secrets and configuration.

### 3) Start the backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API documentation will be available at:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

### 4) Set up the frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend should be served at:

- http://localhost:5173

### 5) Start background workers

Some workflows rely on Celery for transcription and evaluation tasks.

```bash
cd backend
celery -A app.celery_app worker --loglevel=info
```

If you also use scheduled jobs:

```bash
cd backend
celery -A app.celery_app beat --loglevel=info
```

## Environment configuration

The app uses environment variables from `backend/.env`.

The repository includes `backend/.env.example` with the required configuration categories:

- database settings
- JWT secret configuration
- Backblaze B2 credentials
- Gemini API settings
- Celery and Redis settings
- optional discovery and generation integrations

Example:

```env
DATABASE_URL=sqlite:///./interview_coach.db
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
CELERY_BROKER_URL=redis://localhost:6379/0
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-2.5-flash
B2_KEY_ID=your-b2-key-id
B2_APPLICATION_KEY=your-b2-key
B2_BUCKET_NAME=your-bucket
```

Important: never commit real secrets or API keys to version control.

## Running tests

From the backend directory:

```bash
cd backend
pytest
```

The test suite covers evaluation logic, DB-related behavior, storage service integration, and question-discovery workflows.

## Docker

The repository includes a backend Dockerfile.

```bash
cd backend
docker build -t voxmenter-backend .
docker run -p 8000:8000 --env-file .env voxmenter-backend
```

## Deployment notes

VoxMenter is designed for iterative development and deployment workflows, and the frontend is already hosted publicly on Vercel.

Production considerations include:

- moving from SQLite to PostgreSQL in production
- managing secret variables securely in deployment platforms
- running Redis and Celery workers in production
- provisioning cloud storage for uploaded audio and recordings
- securing AI provider credentials and service access

## Contributing

Contributions are welcome.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run the relevant tests
5. Open a pull request with a clear description

## License

This repository does not currently declare a license. If you plan to distribute or commercialize the project, add an appropriate open-source license before release.

## Acknowledgements

VoxMenter uses open-source libraries and AI services such as:

- FastAPI
- React
- Vite
- SQLAlchemy
- Celery
- Redis
- Faster-Whisper
- Gemini
- Backblaze B2

## Summary

VoxMenter is a practical AI interview coaching platform that blends mock interviews, speech capture, automated evaluation, and progress tracking into one cohesive experience. It is built for users who want to improve spoken communication, interview readiness, and confidence through structured, real-world practice.

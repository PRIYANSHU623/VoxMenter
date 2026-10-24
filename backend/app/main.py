from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware



app = FastAPI(title = "AI interview and Comunication" )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

## Register the routers here
from app.api.auth import router as auth_router
from app.api.questions import router as questions_router
from app.api.practice import router as practice_router
from app.api.recordings import router as recordings_router
from app.api.recordings import legacy_router
from app.api.admin_questions import router as admin_questions_router

#include routers here
app.include_router(auth_router)
app.include_router(questions_router)
app.include_router(practice_router)
app.include_router(recordings_router)
app.include_router(legacy_router)
app.include_router(admin_questions_router)

@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "message": "AI Interview Coach backend is running",
    }

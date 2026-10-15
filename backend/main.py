from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
from typing import Optional
import os

# --- App + CORS (Control Layer Fix) ---
app = FastAPI(title="Talent ATS - Full Suite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SQL Layer: SQLAlchemy + SQLite ---
DATABASE_URL = "sqlite:///./ats.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    location = Column(String)
    required_skills = Column(String)
    description = Column(Text)
    status = Column(String, default="Open") # Draft / Open / Closed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Candidate(Base):
    __tablename__ = "candidates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True)
    source = Column(String, default="Careers Page")
    skills = Column(String)
    resume_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"))
    candidate_id = Column(Integer, ForeignKey("candidates.id"))
    candidate_name = Column(String)
    stage = Column(String, default="Applied") # Applied, Screening, Interview, Offer, Hired, Rejected
    rating = Column(Integer, default=0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# --- Schemas (Service Layer Input) ---
class JobCreate(BaseModel):
    title: str
    location: Optional[str] = ""
    required_skills: Optional[str] = ""
    description: Optional[str] = ""
    status: Optional[str] = "Open"

class CandidateApply(BaseModel):
    job_id: int
    name: str
    email: str
    source: Optional[str] = "Careers Page"
    resume_text: Optional[str] = ""
    skills: Optional[str] = ""

class ApplicationUpdate(BaseModel):
    stage: Optional[str] = None
    rating: Optional[int] = None
    notes: Optional[str] = None

# --- Helper ---
def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        pass

# --- DASHBOARD STATS (Reports - FR-9) ---
@app.get("/dashboard/stats")
def dashboard_stats():
    db = SessionLocal()
    total_candidates = db.query(Candidate).count()
    open_jobs = db.query(Job).filter(Job.status == "Open").count()
    hired_count = db.query(Application).filter(Application.stage == "Hired").count()

    # Source Effectiveness
    sources = {}
    for c in db.query(Candidate).all():
        sources[c.source or "Unknown"] = sources.get(c.source or "Unknown", 0) + 1

    # Pipeline Conversion
    pipeline = {}
    for stage in ["Applied","Screening","Interview","Offer","Hired","Rejected"]:
        pipeline[stage] = db.query(Application).filter(Application.stage == stage).count()

    # Avg Time to Hire (simulated)
    avg_tth = 0
    hired_apps = db.query(Application).filter(Application.stage == "Hired").all()
    if hired_apps:
        # simple calc days diff
        total_days = 0
        for h in hired_apps:
            delta = (h.updated_at - h.created_at).days if h.updated_at and h.created_at else 5
            total_days += max(delta, 1)
        avg_tth = round(total_days / len(hired_apps), 1)

    db.close()
    return {
        "total_candidates": total_candidates,
        "open_jobs": open_jobs,
        "hired_count": hired_count,
        "avg_time_to_hire": avg_tth,
        "source_effectiveness": sources,
        "pipeline_conversion": pipeline
    }

# --- JOB MANAGEMENT (FR-2) - Control Layer ---
@app.post("/jobs")
def create_job(job: JobCreate):
    db = SessionLocal()
    db_job = Job(**job.dict(), created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    db.close()
    print(f"[AUDIT] Job Created: {db_job.title} | Status: {db_job.status}")
    return db_job

@app.get("/jobs")
def list_jobs():
    db = SessionLocal()
    jobs = db.query(Job).order_by(Job.id.desc()).all()
    db.close()
    return jobs

# --- CANDIDATE + APPLICATION (Careers Page + Resume Upload) ---
@app.post("/candidates/apply")
def apply_candidate(data: CandidateApply):
    db = SessionLocal()
    # Duplicate check by email (Service Layer Logic)
    candidate = db.query(Candidate).filter(Candidate.email == data.email).first()
    if not candidate:
        candidate = Candidate(
            name=data.name,
            email=data.email,
            source=data.source,
            skills=data.skills,
            resume_text=data.resume_text,
            created_at=datetime.utcnow()
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        print(f"[EMAIL SIM] Notification sent to {candidate.email} - Application Received")
    else:
        print(f"[DUPLICATE CHECK] Existing candidate found: {candidate.email}")

    # Create Application
    job = db.query(Job).filter(Job.id == data.job_id).first()
    if not job:
        db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    app_obj = Application(
        job_id=data.job_id,
        candidate_id=candidate.id,
        candidate_name=candidate.name,
        stage="Applied",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(app_obj)
    db.commit()
    db.refresh(app_obj)
    db.close()
    return {"message": f"Email notification sent (simulated) to {data.email}", "application_id": app_obj.id, "candidate_id": candidate.id}

@app.get("/candidates")
def list_candidates():
    db = SessionLocal()
    candidates = db.query(Candidate).order_by(Candidate.id.desc()).all()
    db.close()
    return candidates

@app.get("/applications")
def list_applications():
    db = SessionLocal()
    apps = db.query(Application).order_by(Application.id.desc()).all()
    db.close()
    return apps

@app.put("/applications/{app_id}")
def update_application(app_id: int, update: ApplicationUpdate):
    db = SessionLocal()
    app_obj = db.query(Application).filter(Application.id == app_id).first()
    if not app_obj:
        db.close()
        raise HTTPException(status_code=404, detail="Application not found")

    if update.stage:
        app_obj.stage = update.stage
        print(f"[AUDIT] Application #{app_id} moved to {update.stage} at {datetime.utcnow()}")
    if update.rating is not None:
        app_obj.rating = update.rating
    if update.notes is not None:
        app_obj.notes = update.notes

    app_obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(app_obj)
    db.close()
    return app_obj

@app.get("/")
def root():
    return {"message": "Talent ATS Backend Running", "control_layer": "FastAPI Routers", "service_layer": "Business Logic", "sql_layer": "SQLAlchemy + SQLite"}
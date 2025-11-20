import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Candidate as CandidateSchema, Job as JobSchema, ReviewRequest as ReviewRequestSchema, Review as ReviewSchema

# Utility helpers
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(v)
        except Exception:
            raise ValueError("Invalid ObjectId")

def oid_str(oid: Any) -> str:
    return str(oid) if isinstance(oid, ObjectId) else str(oid)


def doc_to_strid(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    doc["_id"] = oid_str(doc.get("_id"))
    return doc


def corporate_email_verified(email: str) -> bool:
    # naive check: reject common free-email domains
    domain = email.split("@")[-1].lower()
    free_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "proton.me", "protonmail.com"}
    return domain not in free_domains and "." in domain and len(domain.split(".")) >= 2


app = FastAPI(title="VeriCred API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/response models
class CreateCandidate(BaseModel):
    name: str
    email: str
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    slug: str

class CandidateOut(CandidateSchema):
    id: str = Field(..., alias="_id")

class CreateJob(BaseModel):
    candidate_id: str
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class JobOut(JobSchema):
    id: str = Field(..., alias="_id")

class CreateReviewRequest(BaseModel):
    candidate_id: str
    job_id: str
    reviewer_email: str
    reviewer_name: Optional[str] = None

class ReviewTokenInfo(BaseModel):
    token: str
    candidate_name: str
    candidate_slug: str
    company: str
    title: str

class SubmitReview(BaseModel):
    reviewer_name: str
    reviewer_title: Optional[str] = None
    reviewer_company: Optional[str] = None
    reviewer_email: str
    overall: int = Field(..., ge=1, le=5)
    skills: Dict[str, int]
    public_text: str
    confirm_manager: bool

class ReviewOut(BaseModel):
    id: str = Field(..., alias="_id")
    candidate_id: str
    job_id: str
    reviewer_name: str
    reviewer_title: Optional[str] = None
    reviewer_company: Optional[str] = None
    reviewer_email: str
    overall: int
    skills: Dict[str, int]
    public_text: str
    verified_corporate_email: bool
    verification_checked: bool
    approved_by_candidate: bool

class ApproveReview(BaseModel):
    approve: bool


# Health endpoints
@app.get("/")
def read_root():
    return {"service": "VeriCred Backend", "status": "ok"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set",
        "database_name": "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# Candidates
@app.post("/api/candidates")
def create_candidate(payload: CreateCandidate):
    # ensure unique slug
    existing = db["candidate"].find_one({"slug": payload.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Slug already in use")
    cid = create_document("candidate", CandidateSchema(**payload.model_dump()))
    doc = db["candidate"].find_one({"_id": ObjectId(cid)})
    return doc_to_strid(doc)

@app.get("/api/candidates/{candidate_id}")
def get_candidate(candidate_id: str):
    doc = db["candidate"].find_one({"_id": ObjectId(candidate_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return doc_to_strid(doc)


# Jobs
@app.post("/api/jobs")
def create_job(payload: CreateJob):
    # ensure candidate exists
    cand = db["candidate"].find_one({"_id": ObjectId(payload.candidate_id)})
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    jid = create_document("job", JobSchema(**payload.model_dump()))
    doc = db["job"].find_one({"_id": ObjectId(jid)})
    return doc_to_strid(doc)

@app.get("/api/candidates/{candidate_id}/jobs")
def list_jobs(candidate_id: str):
    jobs = get_documents("job", {"candidate_id": candidate_id})
    return [doc_to_strid(j) for j in jobs]


# Review Requests
@app.post("/api/review-requests")
def create_review_request(payload: CreateReviewRequest):
    # Validate candidate and job
    cand = db["candidate"].find_one({"_id": ObjectId(payload.candidate_id)})
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = db["job"].find_one({"_id": ObjectId(payload.job_id)})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    token = secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    data = ReviewRequestSchema(
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        reviewer_name=payload.reviewer_name,
        reviewer_email=payload.reviewer_email,
        token=token,
        status="pending",
        expires_at=expires,
    )
    rrid = create_document("reviewrequest", data)
    # In a real app, send email here with token link
    return {"_id": rrid, "token": token}

@app.get("/api/review-requests/{token}")
def get_request_by_token(token: str):
    req = db["reviewrequest"].find_one({"token": token, "status": "pending"})
    if not req:
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    job = db["job"].find_one({"_id": ObjectId(req["job_id"])})
    cand = db["candidate"].find_one({"_id": ObjectId(req["candidate_id"])})
    return ReviewTokenInfo(
        token=token,
        candidate_name=cand["name"],
        candidate_slug=cand["slug"],
        company=job["company"],
        title=job["title"],
    )


# Reviews
@app.post("/api/reviews/{token}")
def submit_review(token: str, payload: SubmitReview):
    req = db["reviewrequest"].find_one({"token": token})
    if not req or req.get("status") not in {"pending"}:
        raise HTTPException(status_code=404, detail="Invalid or used token")
    if not payload.confirm_manager:
        raise HTTPException(status_code=400, detail="You must confirm you were the manager")

    verified_email = corporate_email_verified(payload.reviewer_email)

    review = ReviewSchema(
        candidate_id=req["candidate_id"],
        job_id=req["job_id"],
        reviewer_name=payload.reviewer_name,
        reviewer_title=payload.reviewer_title,
        reviewer_company=payload.reviewer_company,
        reviewer_email=payload.reviewer_email,
        overall=payload.overall,
        skills=payload.skills,
        public_text=payload.public_text,
        verified_corporate_email=verified_email,
        verification_checked=True,
        approved_by_candidate=False,
    )
    rid = create_document("review", review)

    # mark request as submitted
    db["reviewrequest"].update_one({"_id": req["_id"]}, {"$set": {"status": "submitted", "used_at": datetime.now(timezone.utc)}})

    doc = db["review"].find_one({"_id": ObjectId(rid)})
    return doc_to_strid(doc)


@app.post("/api/reviews/{review_id}/approve")
def approve_review(review_id: str, payload: ApproveReview):
    review = db["review"].find_one({"_id": ObjectId(review_id)})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    db["review"].update_one({"_id": review["_id"]}, {"$set": {"approved_by_candidate": bool(payload.approve), "updated_at": datetime.now(timezone.utc)}})
    review = db["review"].find_one({"_id": ObjectId(review_id)})
    return doc_to_strid(review)


# Public profile
@app.get("/api/profile/{slug}")
def public_profile(slug: str):
    cand = db["candidate"].find_one({"slug": slug})
    if not cand:
        raise HTTPException(status_code=404, detail="Profile not found")
    jobs = list(db["job"].find({"candidate_id": oid_str(cand["_id"])}))
    job_ids = {oid_str(j["_id"]) for j in jobs}
    reviews = list(db["review"].find({
        "candidate_id": oid_str(cand["_id"]),
        "approved_by_candidate": True
    }))
    # attach job info to reviews
    jobs_by_id = {oid_str(j["_id"]): j for j in jobs}
    for r in reviews:
        r["job"] = jobs_by_id.get(r["job_id"]) or {}
    return {
        "candidate": doc_to_strid(cand),
        "jobs": [doc_to_strid(j) for j in jobs],
        "reviews": [doc_to_strid(r) for r in reviews]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

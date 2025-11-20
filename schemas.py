"""
Database Schemas for VeriCred

Each Pydantic model represents a collection in MongoDB. The collection
name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, List

class Candidate(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    bio: Optional[str] = Field(None, description="Short bio")
    photo_url: Optional[str] = Field(None, description="Profile photo URL")
    slug: str = Field(..., description="Public profile slug (unique)")

class Job(BaseModel):
    candidate_id: str = Field(..., description="Reference to candidate _id (string)")
    company: str = Field(..., description="Company name")
    title: str = Field(..., description="Job title")
    start_date: Optional[str] = Field(None, description="Start date (YYYY-MM)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM or 'Present')")

class ReviewRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate _id")
    job_id: str = Field(..., description="Job _id")
    reviewer_name: Optional[str] = Field(None, description="Manager name")
    reviewer_email: str = Field(..., description="Manager work email")
    token: str = Field(..., description="Secure one-time token")
    status: str = Field("pending", description="pending | submitted | approved | rejected")
    expires_at: Optional[str] = Field(None, description="ISO timestamp for expiration")

class Review(BaseModel):
    candidate_id: str = Field(...)
    job_id: str = Field(...)
    reviewer_name: str = Field(...)
    reviewer_title: Optional[str] = Field(None)
    reviewer_company: Optional[str] = Field(None)
    reviewer_email: str = Field(...)
    overall: int = Field(..., ge=1, le=5)
    skills: Dict[str, int] = Field(..., description="skill_name -> rating (1-5)")
    public_text: str = Field(..., description="Public testimonial text")
    verified_corporate_email: bool = Field(False, description="True if email domain appears corporate")
    verification_checked: bool = Field(False, description="Manual/auto verification done")
    approved_by_candidate: bool = Field(False, description="Candidate approved for public profile")

# Helper response models (optional for documentation)
class PublicProfile(BaseModel):
    candidate: Candidate
    jobs: List[Job]
    reviews: List[Review]

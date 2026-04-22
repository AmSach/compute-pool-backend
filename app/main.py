from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_, create_engine
from datetime import datetime, timedelta
from typing import Optional
import uuid, hashlib, os

from app.database import get_db
from app.models import Base, User, Node, Job, Transaction, AuditLog, NodeStatus, JobStatus, UserTier

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_cNbr6p8mPvqH@ep-frosty-rice-aoea3obe.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5)

app = FastAPI(title="ComputePool API", version="0.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

Base.metadata.create_all(bind=engine)

GPU_MULT = {
    "rtx-4090": 3.0, "rtx-5090": 3.0, "rtx-3090": 2.5,
    "rtx-4070": 2.5, "rtx-3060": 2.0, "rtx-2070": 2.0,
    "gtx-1080ti": 1.5, "gtx-1080": 1.5, "gtx-1660": 1.3, "cpu": 0.8
}
GEO_RATE = {"in": 0.7, "india": 0.7, "us": 1.0, "uk": 1.0, "eu": 0.95}
PLATFORM_FEE = 0.20
CASHIOUT_MIN = 500.0

def qs(g: str) -> float: return GPU_MULT.get(g.lower(), 1.0)
def gr(r: str) -> float: return GEO_RATE.get(r.lower(), 1.0)

def audit(db: Session, log_type: str, data: dict):
    log = AuditLog(id=uuid.uuid4().hex[:12], type=log_type, data=data)
    db.add(log)

# ── STATUS ────────────────────────────────────────────────
@app.get("/status")
def status_endpoint():
    return {"name": "ComputePool API", "version": "0.1.0", "status": "running"}

# ── AUTH ─────────────────────────────────────────────────
@app.post("/auth/register")
def register(user_id: str, name: str, region: str = "in", db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.id == user_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    tier = UserTier.GOD if user_id == "god" else UserTier.STANDARD
    user = User(id=user_id, name=name, tier=tier, balance=0, region=region)
    db.add(user)
    audit(db, "user_registered", {"user_id": user_id, "name": name})
    db.commit()
    return {"user_id": user_id, "tier": tier.value, "balance": 0}

@app.post("/auth/login")
def login(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id, name=user_id, tier=UserTier.STANDARD)
        db.add(user)
        db.commit()
    return {"user_id": user.id, "tier": user.tier.value, "balance": user.balance}

@app.get("/users/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user.id, "name": user.name, "tier": user.tier.value,
            "balance": user.balance, "earned_total": user.earned_total,
            "spent_total": user.spent_total, "region": user.region}

# ── NODES ────────────────────────────────────────────────
@app.post("/nodes/register")
def register_node(node_name: str, gpu_tier: str, owner_id: str,
                  cpu_cores: int = 4, ram_gb: int = 8, region: str = "in",
                  db: Session = Depends(get_db)):
    node_id = uuid.uuid4().hex[:12]
    quality = qs(gpu_tier)
    node = Node(id=node_id, name=node_name, gpu_tier=gpu_tier, owner_id=owner_id,
                cpu_cores=cpu_cores, ram_gb=ram_gb, quality_score=quality,
                status=NodeStatus.ONLINE, region=region)
    db.add(node)
    audit(db, "node_registered", {"node_id": node_id, "owner_id": owner_id})
    db.commit()
    return {"node_id": node_id, "quality_score": quality}

@app.post("/nodes/heartbeat")
def heartbeat(node_id: str, status: str = None, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    node.last_heartbeat = datetime.utcnow()
    if status:
        node.status = NodeStatus(status.upper())
    db.commit()
    return {"ok": True}

@app.get("/nodes")
def list_nodes(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    return {"nodes": [{"id": n.id, "name": n.name, "gpu_tier": n.gpu_tier,
                       "owner_id": n.owner_id, "status": n.status.value,
                       "quality_score": n.quality_score, "region": n.region,
                       "online": (datetime.utcnow() - n.last_heartbeat).seconds < 90
                       } for n in nodes], "count": len(nodes)}

@app.get("/nodes/{node_id}")
def get_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"node": {"id": node.id, "name": node.name, "gpu_tier": node.gpu_tier,
                     "owner_id": node.owner_id, "status": node.status.value,
                     "quality_score": node.quality_score}}

# ── JOBS ────────────────────────────────────────────────
@app.post("/jobs/submit")
def submit_job(type: str, submitter_id: str, script: str = None,
                slices: int = 1, priority: int = 0,
                db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == submitter_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    gpu_cost = {"ml": 2.5, "gaming": 3.0, "compute": 1.0}.get(type.lower(), 1.0)
    cost = slices * gpu_cost * gr(user.region)
    final_cost = 0.0 if user.tier == UserTier.GOD else cost
    if user.tier != UserTier.GOD and user.balance < final_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {final_cost}, have {user.balance}")
    job_id = uuid.uuid4().hex[:12]
    job = Job(id=job_id, type=type, status=JobStatus.PENDING, submitter_id=submitter_id,
              script=script, slices=slices, credits_cost=final_cost, priority=priority)
    db.add(job)
    if user.tier != UserTier.GOD:
        user.balance -= final_cost
        user.spent_total += final_cost
        tx = Transaction(id=uuid.uuid4().hex[:12], user_id=submitter_id, type="spend",
                         amount=-final_cost, balance_after=user.balance,
                         description=f"Job {job_id} submitted")
        db.add(tx)
    audit(db, "job_submitted", {"job_id": job_id, "type": type, "submitter_id": submitter_id})
    db.commit()
    return {"job_id": job_id, "status": "PENDING", "estimated_cost": final_cost}

@app.get("/jobs")
def list_jobs(status: str = None, submitter_id: str = None, db: Session = Depends(get_db)):
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == JobStatus(status.upper()))
    if submitter_id:
        q = q.filter(Job.submitter_id == submitter_id)
    jobs = q.order_by(Job.created_at.desc()).all()
    return {"jobs": [{"id": j.id, "type": j.type, "status": j.status.value,
                      "submitter_id": j.submitter_id, "assigned_node_id": j.assigned_node_id,
                      "credits_cost": j.credits_cost, "created_at": j.created_at.isoformat()
                      } for j in jobs], "count": len(jobs)}

@app.get("/jobs/next")
def next_job(node_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    job = db.query(Job).filter(Job.status == JobStatus.PENDING).order_by(Job.priority.desc(), Job.created_at.asc()).first()
    if not job:
        return {"job": None, "message": "No jobs available"}
    job.status = JobStatus.ASSIGNED
    job.assigned_node_id = node_id
    job.started_at = datetime.utcnow()
    node.status = NodeStatus.BUSY
    audit(db, "job_assigned", {"job_id": job.id, "node_id": node_id})
    db.commit()
    return {"job": {"id": job.id, "type": job.type, "script": job.script, "slices": job.slices}}

@app.post("/jobs/complete")
def complete_job(job_id: str, result_cid: str = None, error: str = None, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.FAILED if error else JobStatus.COMPLETED
    job.result_cid = result_cid
    job.error = error
    job.completed_at = datetime.utcnow()
    if job.assigned_node_id:
        node = db.query(Node).filter(Node.id == job.assigned_node_id).first()
        if node:
            node.status = NodeStatus.ONLINE
            # Pay node owner
            if job.credits_cost > 0 and not error:
                earn_mult = qs(node.gpu_tier) * gr(node.region)
                earned = job.credits_cost * earn_mult * (1 - PLATFORM_FEE)
                owner = db.query(User).filter(User.id == node.owner_id).first()
                if owner:
                    owner.balance += earned
                    owner.earned_total += earned
                    tx = Transaction(id=uuid.uuid4().hex[:12], user_id=node.owner_id, type="earn",
                                     amount=earned, balance_after=owner.balance,
                                     job_id=job_id, description=f"Job {job_id} completed")
                    db.add(tx)
    audit(db, "job_completed", {"job_id": job_id, "error": error})
    db.commit()
    return {"ok": True}

@app.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": {"id": job.id, "type": job.type, "status": job.status.value,
                    "submitter_id": job.submitter_id, "assigned_node_id": job.assigned_node_id,
                    "credits_cost": job.credits_cost}}

# ── CREDITS ─────────────────────────────────────────────
@app.post("/credits/topup")
def topup(user_id: str, amount: float, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.balance += amount
    tx = Transaction(id=uuid.uuid4().hex[:12], user_id=user_id, type="topup",
                     amount=amount, balance_after=user.balance, description="Top up")
    db.add(tx)
    audit(db, "topup", {"user_id": user_id, "amount": amount})
    db.commit()
    return {"ok": True, "balance": user.balance}

@app.get("/credits/{user_id}")
def get_credits(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user.id, "balance": user.balance, "earned_total": user.earned_total,
            "spent_total": user.spent_total}

@app.get("/credits/leaderboard/top")
def leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.tier != UserTier.GOD).order_by(User.earned_total.desc()).limit(20).all()
    return {"leaderboard": [{"user_id": u.id, "earned_total": round(u.earned_total, 2)} for u in users]}

@app.post("/credits/cashout")
def cashout(user_id: str, amount: float, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    if amount < CASHIOUT_MIN:
        raise HTTPException(status_code=400, detail=f"Minimum cashout Rs.{CASHIOUT_MIN}")
    user.balance -= amount
    tx = Transaction(id=uuid.uuid4().hex[:12], user_id=user_id, type="cashout",
                     amount=-amount, balance_after=user.balance, description="Cashout requested")
    db.add(tx)
    audit(db, "cashout", {"user_id": user_id, "amount": amount})
    db.commit()
    return {"ok": True, "message": f"Cashout Rs.{amount} requested. 24-48hrs."}

@app.get("/logs")
def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return {"logs": [{"type": l.type, "data": l.data, "created_at": l.created_at.isoformat()} for l in logs]}

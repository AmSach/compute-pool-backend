from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime, timedelta
from typing import Optional
import uuid, hashlib, os

from app.config import get_settings
from app.database import get_db, engine
from app.models import Base, User, Node, Job, Transaction, AuditLog, NodeStatus, JobStatus, UserTier

settings = get_settings()
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

def qs(g: str) -> float: return GPU_MULT.get(g.lower(), 1.0)
def gr(r: str) -> float: return GEO_RATE.get(r.lower(), 1.0)
def uid() -> str: return uuid.uuid4().hex[:16]
def log(db: Session, ltype: str, data: dict):
    db.add(AuditLog(id=uid(), type=ltype, data=data))
    db.commit()

# ── AUTH ──────────────────────────────────────────────────────────
@app.post("/auth/register")
def register(payload: dict, db: Session = Depends(get_db)):
    user_id = payload.get("userId") or payload.get("user_id")
    name = payload.get("name")
    region = payload.get("region", "in")
    if not user_id or not name: raise HTTPException(400, "userId and name required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id, name=name, region=region, tier=UserTier.GOD if user_id == "god" else UserTier.STANDARD)
        db.add(user); db.commit(); db.refresh(user)
    token = hashlib.sha256(f"{user_id}{datetime.utcnow()}".encode()).hexdigest()
    return {"token": token, "userId": user.id, "tier": user.tier.value, "balance": user.balance}

@app.post("/auth/login")
def login(payload: dict, db: Session = Depends(get_db)):
    user_id = payload.get("userId") or payload.get("user_id")
    if not user_id: raise HTTPException(400, "userId required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    token = hashlib.sha256(f"{user_id}{datetime.utcnow()}".encode()).hexdigest()
    return {"token": token, "userId": user.id, "tier": user.tier.value, "balance": user.balance}

@app.get("/auth/me")
def me(token: str = Query(...), db: Session = Depends(get_db)):
    # Token lookup simplified; in prod, store sessions in DB
    if not token: raise HTTPException(401, "No token")
    return {"status": "ok"}  # Simplified; plug in session table

# ── NODES ─────────────────────────────────────────────────────────
@app.post("/nodes/register")
def register_node(payload: dict, db: Session = Depends(get_db)):
    node_name = payload.get("nodeName") or payload.get("node_name")
    gpu_tier = payload.get("gpuTier") or payload.get("gpu_tier")
    owner_id = payload.get("ownerId") or payload.get("owner_id")
    cpu_cores = payload.get("cpuCores", 4)
    ram_gb = payload.get("ramGb", 8)
    region = payload.get("region", "in")
    if not node_name or not gpu_tier or not owner_id: raise HTTPException(400, "nodeName, gpuTier, ownerId required")
    owner = db.query(User).filter(User.id == owner_id).first()
    if not owner: raise HTTPException(404, "Owner not found")
    node_id = uid()
    q = qs(gpu_tier)
    node = Node(id=node_id, name=node_name, owner_id=owner_id, gpu_tier=gpu_tier,
                cpu_cores=cpu_cores, ram_gb=ram_gb, quality_score=q, status=NodeStatus.ONLINE,
                region=region, last_heartbeat=datetime.utcnow())
    db.add(node); db.commit()
    log(db, "node_registered", {"nodeId": node_id, "nodeName": node_name, "gpuTier": gpu_tier, "qualityScore": q})
    return {"nodeId": node_id, "qualityScore": q, "message": "Node registered"}

@app.post("/nodes/heartbeat")
def heartbeat(payload: dict, db: Session = Depends(get_db)):
    node_id = payload.get("nodeId") or payload.get("node_id")
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node: raise HTTPException(404, "Node not found")
    node.last_heartbeat = datetime.utcnow()
    if payload.get("status"): node.status = NodeStatus(payload["status"])
    db.commit()
    return {"ok": True, "time": node.last_heartbeat.isoformat()}

@app.get("/nodes")
def list_nodes(db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    nodes = db.query(Node).all()
    result = []
    for n in nodes:
        online = n.last_heartbeat > cutoff and n.status != NodeStatus.OFFLINE
        result.append({
            "id": n.id, "name": n.name, "ownerId": n.owner_id, "gpuTier": n.gpu_tier,
            "cpuCores": n.cpu_cores, "ramGb": n.ram_gb, "qualityScore": n.quality_score,
            "status": n.status.value, "region": n.region, "online": online
        })
    return {"nodes": result, "count": len(result)}

@app.get("/nodes/{node_id}")
def get_node(node_id: str, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node: raise HTTPException(404, "Node not found")
    return {"node": {"id": node.id, "name": node.name, "gpuTier": node.gpu_tier, "status": node.status.value, "qualityScore": node.quality_score}}

# ── JOBS ──────────────────────────────────────────────────────────
@app.post("/jobs/submit")
def submit_job(payload: dict, db: Session = Depends(get_db)):
    job_type = payload.get("type")
    submitter_id = payload.get("submitterId") or payload.get("submitter_id")
    slices = payload.get("slices", 1)
    priority = payload.get("priority", 0)
    script = payload.get("script")
    if not job_type or not submitter_id: raise HTTPException(400, "type and submitterId required")
    user = db.query(User).filter(User.id == submitter_id).first()
    if not user: raise HTTPException(404, "Submitter not found")
    gpu_cost = 2.5 if job_type == "ml" else 3.0 if job_type == "gaming" else 1.0
    cost = slices * gpu_cost * gr(user.region)
    final_cost = 0.0 if user.tier == UserTier.GOD else cost
    if user.tier != UserTier.GOD and user.balance < final_cost:
        raise HTTPException(400, f"Insufficient credits. Required: {final_cost}, Balance: {user.balance}")
    job_id = uid()
    job = Job(id=job_id, type=job_type, submitter_id=submitter_id, script=script,
              slices=slices, credits_cost=final_cost, priority=priority, status=JobStatus.PENDING)
    db.add(job)
    if user.tier != UserTier.GOD:
        user.balance -= final_cost
        user.spent_total += final_cost
        db.add(Transaction(id=uid(), user_id=submitter_id, type="spend", amount=final_cost,
                          balance_after=user.balance, description=f"Job {job_id} submitted"))
    db.commit()
    log(db, "job_submitted", {"jobId": job_id, "type": job_type, "submitterId": submitter_id, "creditsCost": final_cost})
    return {"jobId": job_id, "status": "pending", "estimatedCost": final_cost}

@app.get("/jobs/next")
def next_job(node_id: str = Query(...), db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node: raise HTTPException(404, "Node not found")
    pending = db.query(Job).filter(Job.status == JobStatus.PENDING).order_by(Job.priority.desc(), Job.created_at).first()
    if not pending: return {"job": None}
    pending.status = JobStatus.ASSIGNED
    pending.assigned_node_id = node_id
    node.status = NodeStatus.BUSY
    db.commit()
    log(db, "job_assigned", {"jobId": pending.id, "nodeId": node_id})
    return {"job": {
        "id": pending.id, "type": pending.type, "status": pending.status.value,
        "script": pending.script, "slices": pending.slices, "priority": pending.priority
    }}

@app.post("/jobs/{job_id}/complete")
def complete_job(job_id: str, payload: dict, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job: raise HTTPException(404, "Job not found")
    error = payload.get("error")
    job.status = JobStatus.FAILED if error else JobStatus.COMPLETED
    job.completed_at = datetime.utcnow()
    job.result_cid = payload.get("resultCid")
    job.error = error
    if job.assigned_node_id:
        node = db.query(Node).filter(Node.id == job.assigned_node_id).first()
        if node: node.status = NodeStatus.ONLINE
    if not error and job.assigned_node_id and job.credits_cost > 0:
        node = db.query(Node).filter(Node.id == job.assigned_node_id).first()
        if node:
            earn_mult = qs(node.gpu_tier) * gr(node.region)
            earned = job.credits_cost * earn_mult * (1 - settings.PLATFORM_FEE)
            owner = db.query(User).filter(User.id == node.owner_id).first()
            if owner:
                owner.balance += earned
                owner.earned_total += earned
                db.add(Transaction(id=uid(), user_id=owner.id, type="earn", amount=earned,
                                  job_id=job_id, balance_after=owner.balance,
                                  description=f"Earnings for job {job_id}"))
    db.commit()
    log(db, "job_completed", {"jobId": job_id, "status": job.status.value})
    return {"ok": True}

@app.get("/jobs")
def list_jobs(status: Optional[str] = None, submitter_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Job)
    if status: q = q.filter(Job.status == JobStatus(status))
    if submitter_id: q = q.filter(Job.submitter_id == submitter_id)
    jobs = q.order_by(Job.created_at.desc()).all()
    return {"jobs": [{"id": j.id, "type": j.type, "status": j.status.value, "submitterId": j.submitter_id,
                      "assignedNodeId": j.assigned_node_id, "creditsCost": j.credits_cost,
                      "createdAt": j.created_at.isoformat()} for j in jobs], "count": len(jobs)}

@app.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job: raise HTTPException(404, "Job not found")
    return {"job": {"id": job.id, "type": job.type, "status": job.status.value, "creditsCost": job.credits_cost}}

# ── CREDITS ───────────────────────────────────────────────────────
@app.post("/credits/topup")
def topup(payload: dict, db: Session = Depends(get_db)):
    user_id = payload.get("userId") or payload.get("user_id")
    amount = float(payload.get("amount", 0))
    if not user_id or amount <= 0: raise HTTPException(400, "userId and amount required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    user.balance += amount
    db.add(Transaction(id=uid(), user_id=user_id, type="topup", amount=amount, balance_after=user.balance))
    db.commit()
    return {"ok": True, "balance": user.balance}

@app.post("/credits/cashout")
def cashout(payload: dict, db: Session = Depends(get_db)):
    user_id = payload.get("userId") or payload.get("user_id")
    amount = float(payload.get("amount", 0))
    if not user_id or amount <= 0: raise HTTPException(400, "userId and amount required")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    if user.balance < settings.CASHIOUT_MIN: raise HTTPException(400, f"Minimum cashout Rs.{settings.CASHIOUT_MIN}")
    if user.balance < amount: raise HTTPException(400, "Insufficient balance")
    user.balance -= amount
    db.add(Transaction(id=uid(), user_id=user_id, type="cashout", amount=amount, balance_after=user.balance))
    db.commit()
    return {"ok": True, "message": f"Cashout Rs.{amount} requested. 24-48hrs."}

@app.get("/credits/{user_id}")
def get_credits(user_id: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    return {"userId": user.id, "balance": user.balance, "earnedTotal": user.earned_total, "tier": user.tier.value}

@app.get("/credits/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).filter(User.tier != UserTier.GOD).order_by(User.earned_total.desc()).limit(20).all()
    return {"leaderboard": [{"userId": u.id, "earnedTotal": round(u.earned_total, 2)} for u in users]}

# ── STATUS ────────────────────────────────────────────────────────
@app.get("/status")
def status(db: Session = Depends(get_db)):
    return {
        "name": "ComputePool Hub", "version": "0.1.0", "status": "running",
        "nodes": db.query(Node).count(), "jobs": db.query(Job).count()
    }

@app.get("/logs")
def logs(limit: int = 50, ltype: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    if ltype: q = q.filter(AuditLog.type == ltype)
    logs = q.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return {"logs": [{"type": l.type, "data": l.data, "ts": l.created_at.isoformat()} for l in logs], "count": len(logs)}

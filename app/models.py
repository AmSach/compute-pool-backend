from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, Text, Enum as SAEnum, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()

class UserTier(str, enum.Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    GOD = "GOD"

class NodeStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"

class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    tier = Column(SAEnum(UserTier), default=UserTier.STANDARD)
    balance = Column(Float, default=0.0)
    earned_total = Column(Float, default=0.0)
    spent_total = Column(Float, default=0.0)
    region = Column(String, default="in")
    created_at = Column(DateTime, default=datetime.utcnow)
    nodes = relationship("Node", back_populates="owner")
    jobs = relationship("Job", back_populates="submitter")

class Node(Base):
    __tablename__ = "nodes"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    owner_id = Column(String, ForeignKey("users.id"))
    gpu_tier = Column(String, nullable=False)
    cpu_cores = Column(Integer, default=4)
    ram_gb = Column(Integer, default=8)
    quality_score = Column(Float, default=1.0)
    status = Column(SAEnum(NodeStatus), default=NodeStatus.OFFLINE)
    region = Column(String, default="in")
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    owner = relationship("User", back_populates="nodes")
    jobs = relationship("Job", back_populates="assigned_node")

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    status = Column(SAEnum(JobStatus), default=JobStatus.PENDING)
    submitter_id = Column(String, ForeignKey("users.id"))
    assigned_node_id = Column(String, ForeignKey("nodes.id"), nullable=True)
    script = Column(Text, nullable=True)
    slices = Column(Integer, default=1)
    completed_slices = Column(Integer, default=0)
    credits_cost = Column(Float, default=0.0)
    priority = Column(Integer, default=0)
    result_cid = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    submitter = relationship("User", back_populates="jobs")
    assigned_node = relationship("Node", back_populates="jobs")

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    type = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=True)
    balance_after = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

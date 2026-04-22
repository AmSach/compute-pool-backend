"""Run once to initialize the database with seed data."""
import sys
sys.path.insert(0, ".")
from app.models import Base, User, UserTier, Node, NodeStatus
from app.database import engine

def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")
    
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        # Create god account
        god = db.query(User).filter(User.user_id == "god").first()
        if not god:
            god = User(user_id="god", name="Aman Sachan", tier=UserTier.GOD, region="in", balance=99999)
            db.add(god)
            print("God user created!")
        else:
            god.tier = UserTier.GOD
            god.balance = 99999
            print("God user updated!")
        
        # Create demo user
        demo = db.query(User).filter(User.user_id == "demo").first()
        if not demo:
            demo = User(user_id="demo", name="Demo User", tier=UserTier.STANDARD, region="in", balance=100)
            db.add(demo)
            print("Demo user created!")
        
        db.commit()
        print("Seed data done!")
    finally:
        db.close()

if __name__ == "__main__":
    init()

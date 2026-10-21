# from sqlalchemy import Column, Integer, Boolen, String ,Text, DateTime
# from sqlalchemy.sql import func
# from app.db.session import Base

# class Question(Base):
#     __tablename__ = "questions"
    
#     id = Column(Integer, primary_key = True, index=True)
#     title = Column(String)
#     category = Column(String)
#     difficulty = Column(Integer)
#     content = Column(String, nullable=False)
#     expected_points = Column(Integer)
#     created_at = Column(DateTime(timezone=True), server_default=func.now())  



from sqlalchemy import Boolean, Column, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.session import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    category = Column(String(100), index=True, nullable=False)
    difficulty = Column(String(50), default="Beginner", nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)

    # One question can be used in many practice sessions.
    practice_sessions = relationship(
        "PracticeSession",
        back_populates="question",
    )
  
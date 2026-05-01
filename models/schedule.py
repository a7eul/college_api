from pydantic import BaseModel
from typing import Optional
from datetime import date, time

class ScheduleItem(BaseModel):
    id: int
    lesson_date: date        
    start_time: time        
    end_time: time             
    subject: str
    teacher: Optional[str] = None
    room: Optional[str] = None
    group_id: int
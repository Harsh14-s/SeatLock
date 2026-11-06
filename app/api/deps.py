from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

# Re-export get_db dependency for clean imports across routers
DatabaseSession = Depends(get_db)

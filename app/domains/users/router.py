from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.domains.users.service import UserService
from app.domains.users.schemas import UserCreate, TokenResponse, UserResponse


router = APIRouter()


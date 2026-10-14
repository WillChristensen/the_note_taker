from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import Membership, Team, TeamRole, User
from app.schemas import TeamCreate, TeamRead

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post(
    "",
    response_model=TeamRead,
    status_code=status.HTTP_201_CREATED,
)
def create_team(
    team_data: TeamCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Team:
    team = Team(name=team_data.name, creator=current_user)
    db.add(team)
    db.flush()
    db.add(
        Membership(
            team_id=team.id,
            user_id=current_user.id,
            role=TeamRole.OWNER,
        )
    )
    db.commit()
    db.refresh(team)
    return team


@router.get("", response_model=list[TeamRead])
def list_teams(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Team]:
    statement = (
        select(Team)
        .join(Membership, Membership.team_id == Team.id)
        .where(
            Membership.user_id == current_user.id,
            Team.deleted_at.is_(None),
        )
        .order_by(Team.created_at.desc(), Team.id.desc())
    )
    return list(db.scalars(statement).all())

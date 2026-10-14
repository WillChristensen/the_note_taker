from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import Membership, Note, Team, TeamRole, User
from app.schemas import (
    MemberAdd,
    MemberRead,
    NoteCreate,
    NoteRead,
    NoteUpdate,
    TeamCreate,
    TeamRead,
)

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


@router.post(
    "/{team_id}/notes",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
)
def create_note(
        team_id: int,
        note_data: NoteCreate,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> Note:
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    membership_exists = db.scalar(
        select(Membership.id).where(
            Membership.team_id == team_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership_exists is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team membership required",
        )

    note = Note(
        team_id=team_id,
        author_id=current_user.id,
        title=note_data.title,
        content=note_data.content,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/{team_id}/notes", response_model=list[NoteRead])
def list_team_notes(
        team_id: int,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> list[Note]:
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    membership_exists = db.scalar(
        select(Membership.id).where(
            Membership.team_id == team_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership_exists is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team membership required",
        )

    statement = (
        select(Note)
        .where(Note.team_id == team_id)
        .order_by(Note.created_at.desc(), Note.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


@router.get("/{team_id}/notes/{note_id}", response_model=NoteRead)
def get_team_note(
        team_id: int,
        note_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> Note:
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    membership_exists = db.scalar(
        select(Membership.id).where(
            Membership.team_id == team_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership_exists is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team membership required",
        )

    note = db.scalar(
        select(Note).where(Note.id == note_id, Note.team_id == team_id)
    )
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    return note


@router.patch("/{team_id}/notes/{note_id}", response_model=NoteRead)
def update_team_note(
        team_id: int,
        note_id: int,
        note_data: NoteUpdate,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> Note:
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    membership_exists = db.scalar(
        select(Membership.id).where(
            Membership.team_id == team_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership_exists is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team membership required",
        )

    note = db.scalar(
        select(Note).where(Note.id == note_id, Note.team_id == team_id)
    )
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    for field, value in note_data.model_dump(exclude_unset=True).items():
        setattr(note, field, value)
    db.commit()
    db.refresh(note)
    return note


@router.delete(
    "/{team_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_team_note(
        team_id: int,
        note_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> None:
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    membership_exists = db.scalar(
        select(Membership.id).where(
            Membership.team_id == team_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership_exists is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team membership required",
        )

    note = db.scalar(
        select(Note).where(Note.id == note_id, Note.team_id == team_id)
    )
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    db.delete(note)
    db.commit()


def require_active_owner(
        team_id: int,
        current_user: User,
        db: Session,
) -> Team:
    team = db.scalar(
        select(Team).where(Team.id == team_id, Team.deleted_at.is_(None))
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    membership = db.scalar(
        select(Membership).where(
            Membership.team_id == team_id,
            Membership.user_id == current_user.id,
        )
    )
    if membership is None or membership.role is not TeamRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owners can manage memberships",
        )
    return team


@router.get("/{team_id}/members", response_model=list[MemberRead])
def list_team_members(
        team_id: int,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> list[MemberRead]:
    require_active_owner(team_id, current_user, db)
    rows = db.execute(
        select(Membership.user_id, User.email, Membership.role, Membership.joined_at)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.team_id == team_id,
            User.deleted_at.is_(None),
        )
        .order_by(Membership.joined_at, Membership.id)
    )
    return [
        MemberRead(
            user_id=user_id,
            email=email,
            role=role.value,
            joined_at=joined_at,
        )
        for user_id, email, role, joined_at in rows
    ]


@router.post(
    "/{team_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_team_member(
        team_id: int,
        member_data: MemberAdd,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
) -> MemberRead:
    team = require_active_owner(team_id, current_user, db)
    email = str(member_data.email)
    user = db.scalar(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active user not found",
        )

    existing_membership = db.scalar(
        select(Membership).where(
            Membership.team_id == team.id,
            Membership.user_id == user.id,
        )
    )
    if existing_membership is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this team",
        )

    membership = Membership(team=team, user=user, role=TeamRole.MEMBER)
    db.add(membership)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_membership = db.scalar(
            select(Membership.id).where(
                Membership.team_id == team.id,
                Membership.user_id == user.id,
            )
        )
        if existing_membership is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this team",
            ) from None
        raise
    db.refresh(membership)
    return MemberRead(
        user_id=user.id,
        email=user.email,
        role=membership.role.value,
        joined_at=membership.joined_at,
    )

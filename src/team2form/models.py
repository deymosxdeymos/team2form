from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from pydantic_core import PydanticCustomError


class Team2FormModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')


class Personality(Team2FormModel):
    ei: float = Field(ge=-1, le=1)
    sn: float = Field(ge=-1, le=1)
    tf: float = Field(ge=-1, le=1)
    pj: float = Field(ge=-1, le=1)


class PersonSkill(Team2FormModel):
    id: str = Field(min_length=1)
    level: float = Field(ge=0, le=1)


class PersonPreference(Team2FormModel):
    person_id: str = Field(alias='personId', min_length=1)
    preference: float = Field(ge=0, le=1)


class Person(Team2FormModel):
    id: str = Field(min_length=1)
    gender: Literal['FEMALE', 'MALE'] | None = None
    personality: Personality
    skills: list[PersonSkill] = Field(default_factory=list)
    preferences: list[PersonPreference] | None = None

    @model_validator(mode='after')
    def validate_unique_preference_person_ids(self) -> Person:
        duplicate_preferences = duplicate_preference_person_ids(self.preferences)
        if duplicate_preferences:
            raise PydanticCustomError(
                'duplicate_person_preference_ids',
                'person preferences must not contain duplicate personIds',
                {'person_ids': duplicate_preferences},
            )
        return self


class TaskSkill(Team2FormModel):
    id: str = Field(min_length=1)
    level: float = Field(ge=0, le=1)
    importance: float = Field(ge=1)


class TaskPreference(Team2FormModel):
    person_id: str = Field(alias='personId', min_length=1)
    preference: float = Field(ge=0, le=1)


class Task(Team2FormModel):
    id: str = Field(min_length=1)
    team_size: int = Field(alias='teamSize', ge=2)
    skills: list[TaskSkill] = Field(min_length=1)
    preferences: list[TaskPreference] | None = None

    @model_validator(mode='after')
    def validate_unique_preference_person_ids(self) -> Task:
        duplicate_preferences = duplicate_preference_person_ids(self.preferences)
        if duplicate_preferences:
            raise PydanticCustomError(
                'duplicate_task_preference_ids',
                'task preferences must not contain duplicate personIds',
                {'person_ids': duplicate_preferences},
            )
        return self


class Similarity(Team2FormModel):
    source_id: str = Field(alias='sourceId', min_length=1)
    target_id: str = Field(alias='targetId', min_length=1)
    similarity: float = Field(ge=0, le=1)


class FormationRequest(Team2FormModel):
    people: list[Person] = Field(min_length=2)
    tasks: list[Task] = Field(min_length=1)
    init_random: bool = Field(default=False, alias='initRandom')
    alpha: float | None = Field(default=None, ge=0, le=1)
    beta: float | None = Field(default=None, ge=0, le=1)
    gamma: float | None = Field(default=None, ge=0, le=1)
    delta: float | None = Field(default=None, ge=0, le=1)
    similarities: list[Similarity] | None = None

    @computed_field
    @property
    def total_requested_seats(self) -> int:
        return sum(task.team_size for task in self.tasks)

    @model_validator(mode='after')
    def validate_unique_ids(self) -> FormationRequest:
        duplicate_people = duplicate_ids(person.id for person in self.people)
        if duplicate_people:
            duplicates = ', '.join(duplicate_people)
            raise ValueError(f'people ids must be unique: {duplicates}')

        duplicate_tasks = duplicate_ids(task.id for task in self.tasks)
        if duplicate_tasks:
            duplicates = ', '.join(duplicate_tasks)
            raise ValueError(f'task ids must be unique: {duplicates}')

        person_ids = {person.id for person in self.people}
        for person in self.people:
            unknown_preferences = unknown_preference_person_ids(
                person.preferences,
                person_ids,
            )
            if unknown_preferences:
                raise PydanticCustomError(
                    'unknown_person_preference_person_ids',
                    'person preferences reference unknown people ids',
                    {
                        'person_id': person.id,
                        'person_ids': unknown_preferences,
                    },
                )

        for task in self.tasks:
            unknown_preferences = unknown_preference_person_ids(
                task.preferences,
                person_ids,
            )
            if unknown_preferences:
                raise PydanticCustomError(
                    'unknown_task_preference_person_ids',
                    'task preferences reference unknown people ids',
                    {
                        'task_id': task.id,
                        'person_ids': unknown_preferences,
                    },
                )

        return self


class BackgroundFormationRequest(FormationRequest):
    reply_post_url: str = Field(alias='replyPostUrl', min_length=1)


class TeamMember(Person):
    task_preference: float | None = Field(
        default=None,
        alias='taskPreference',
        ge=0,
        le=1,
    )


class TeamQualityRequest(Team2FormModel):
    task_skills: list[TaskSkill] = Field(alias='taskSkills', min_length=1)
    team: list[TeamMember] = Field(min_length=2)
    alpha: float | None = Field(default=None, ge=0, le=1)
    beta: float | None = Field(default=None, ge=0, le=1)
    gamma: float | None = Field(default=None, ge=0, le=1)
    delta: float | None = Field(default=None, ge=0, le=1)
    similarities: list[Similarity] | None = None

    @model_validator(mode='after')
    def validate_unique_team_member_ids(self) -> TeamQualityRequest:
        duplicate_members = duplicate_ids(member.id for member in self.team)
        if duplicate_members:
            duplicates = ', '.join(duplicate_members)
            raise ValueError(f'team member ids must be unique: {duplicates}')

        member_ids = {member.id for member in self.team}
        for member in self.team:
            unknown_preferences = unknown_preference_person_ids(
                member.preferences,
                member_ids,
            )
            if unknown_preferences:
                raise PydanticCustomError(
                    'unknown_person_preference_person_ids',
                    'person preferences reference unknown people ids',
                    {
                        'person_id': member.id,
                        'person_ids': unknown_preferences,
                    },
                )
        return self


class AssignedPerson(Team2FormModel):
    id: str = Field(min_length=1)
    skill_ids: list[str] = Field(alias='skillIds')


class TeamResult(Team2FormModel):
    task_id: str = Field(alias='taskId', min_length=1)
    people: list[AssignedPerson] = Field(min_length=1)
    quality: float


class TeamsResponse(Team2FormModel):
    teams: list[TeamResult] = Field(min_length=1)


class QualityBreakdown(Team2FormModel):
    quality: float
    skill_score: float = Field(alias='skillScore')
    personality_score: float = Field(alias='personalityScore')
    task_preference_score: float = Field(alias='taskPreferenceScore')
    social_score: float = Field(alias='socialScore')
    weights: dict[str, float]
    assignments: dict[str, list[str]]


def dump_json(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(
        mode='json',
        by_alias=True,
        exclude_computed_fields=True,
    )


def duplicate_ids(ids: Iterable[str]) -> list[str]:
    counts = Counter(ids)
    return sorted(identifier for identifier, count in counts.items() if count > 1)


def duplicate_preference_person_ids(
    preferences: list[PersonPreference] | list[TaskPreference] | None,
) -> list[str]:
    if not preferences:
        return []
    return duplicate_ids(preference.person_id for preference in preferences)


def unknown_preference_person_ids(
    preferences: list[PersonPreference] | list[TaskPreference] | None,
    known_person_ids: set[str],
) -> list[str]:
    if not preferences:
        return []
    return sorted(
        {
            preference.person_id
            for preference in preferences
            if preference.person_id not in known_person_ids
        }
    )

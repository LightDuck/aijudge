from typing import Literal

from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question: str
    mode: Literal["card", "ruling"] | None = None


class ClarificationItemModel(BaseModel):
    kind: str
    text: str


class AnswerRequest(BaseModel):
    question: str
    items: list[ClarificationItemModel]
    answers: list[str]
    mode: Literal["card", "ruling"] | None = None


class CitationModel(BaseModel):
    label: str
    text: str


class ResultResponse(BaseModel):
    status: str
    text: str
    citations: list[CitationModel] | None = None
    mode: Literal["card", "ruling"]


class NeedsClarificationResponse(BaseModel):
    status: str
    question: str
    items: list[ClarificationItemModel]
    mode: Literal["card", "ruling"]

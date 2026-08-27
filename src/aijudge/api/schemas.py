from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question: str


class ClarificationItemModel(BaseModel):
    kind: str
    text: str


class AnswerRequest(BaseModel):
    question: str
    items: list[ClarificationItemModel]
    answers: list[str]

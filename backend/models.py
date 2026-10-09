from datetime import date
from typing import List, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Login(Model):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    @field_validator('email')
    @classmethod
    def email_format(cls, v):
        if '@' not in v or any(c.isspace() for c in v):
            raise ValueError('유효한 이메일을 입력해 주세요.')
        return v.lower()

class Register(Login):
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    company: str = Field(min_length=1, max_length=120)
    product: str = Field(default='', max_length=120)

class Company(Model):
    name: str = Field(min_length=1, max_length=120)
    product: str = Field(default='', max_length=120)

class Assessment(Model):
    company_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=150)
    deadline: date

class Version(Model):
    version: int = Field(gt=0)

class Answer(Model):
    question_id: str
    answer: str = Field(default='', max_length=2000)
    note: str = Field(default='', max_length=2000)

class Answers(Version):
    answers: List[Answer] = Field(max_length=20)

class Review(Version):
    status: Literal['approved','rejected']
    reason: str = Field(default='', max_length=2000)

class Generate(Version):
    mode: Literal['template','ai'] = 'template'

class Report(Version):
    body: str = Field(min_length=1, max_length=30000)

QUESTIONS = [
    {'id':'L1','category':'노동','text':'초과 근무 급여 비율과 관련 관리 방법을 설명해 주세요.'},
    {'id':'E1','category':'환경','text':'최근 에너지 사용량과 환경 관리 개선 계획을 설명해 주세요.'},
    {'id':'H1','category':'건강 및 안전','text':'안전 교육 및 사고 예방 활동을 설명해 주세요.'},
    {'id':'ET1','category':'윤리','text':'하위 협력사 행동 강령 및 실사 이행 방법을 설명해 주세요.'},
]
EVIDENCE_KINDS = {'labor':'근로 관련 증빙','environment':'환경 관련 증빙','safety':'안전 관련 증빙','ethics':'공급망 행동 강령 증빙'}

class DocumentQuestion(Model):
    question: str = Field(min_length=2, max_length=500)
    generate: bool = False

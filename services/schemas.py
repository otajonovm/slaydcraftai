from pydantic import BaseModel, Field

LAYOUT_TYPES = ("title", "bullet_points", "comparison", "quote", "summary")
LANGUAGES = ("uz", "ru", "en")


class Slide(BaseModel):
    slide_number: int = 0
    layout_type: str = "bullet_points"
    title: str = ""
    subtitle: str = ""
    bullet_points: list[str] = Field(default_factory=list)
    left_title: str = ""
    right_title: str = ""
    left_points: list[str] = Field(default_factory=list)
    right_points: list[str] = Field(default_factory=list)
    quote: str = ""
    quote_author: str = ""
    speaker_notes: str = ""


class PresentationContent(BaseModel):
    presentation_title: str
    slides: list[Slide]
    language: str = "uz"


class ReferatSection(BaseModel):
    title: str
    paragraphs: list[str] = Field(default_factory=list)


class ReferatChapter(BaseModel):
    title: str
    sections: list[ReferatSection] = Field(default_factory=list)


class ReferatContent(BaseModel):
    title: str
    introduction: list[str] = Field(default_factory=list)
    chapters: list[ReferatChapter] = Field(default_factory=list)
    conclusion: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class ReferatMeta(BaseModel):
    work_type: str = "referat"          # referat | mustaqil
    institution_type: str = "otm"       # otm | college | school
    institution: str = ""
    student: str = ""
    teacher: str = ""
    city: str = "Toshkent"
    year: int
    language: str = "uz"


ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")

DOC_LABELS: dict[str, dict] = {
    "uz": {
        "ministry": {
            "otm": "O'ZBEKISTON RESPUBLIKASI OLIY TA'LIM, FAN VA INNOVATSIYALAR VAZIRLIGI",
            "college": "O'ZBEKISTON RESPUBLIKASI OLIY TA'LIM, FAN VA INNOVATSIYALAR VAZIRLIGI",
            "school": "O'ZBEKISTON RESPUBLIKASI MAKTABGACHA VA MAKTAB TA'LIMI VAZIRLIGI",
        },
        "work": {"referat": "REFERAT", "mustaqil": "MUSTAQIL ISH"},
        "topic": "Mavzu:",
        "done_by": "Bajardi:",
        "checked_by": "Qabul qildi:",
        "contents": "REJA",
        "intro": "KIRISH",
        "conclusion": "XULOSA",
        "references": "FOYDALANILGAN ADABIYOTLAR RO'YXATI",
        "chapter": "{roman} BOB.",
        "presentation": "TAQDIMOT",
        "thanks": "E'tiboringiz uchun rahmat!",
        "questions": "Savollaringiz bormi?",
        "summary": "Xulosa",
    },
    "ru": {
        "ministry": {
            "otm": "МИНИСТЕРСТВО ВЫСШЕГО ОБРАЗОВАНИЯ, НАУКИ И ИННОВАЦИЙ РЕСПУБЛИКИ УЗБЕКИСТАН",
            "college": "МИНИСТЕРСТВО ВЫСШЕГО ОБРАЗОВАНИЯ, НАУКИ И ИННОВАЦИЙ РЕСПУБЛИКИ УЗБЕКИСТАН",
            "school": "МИНИСТЕРСТВО ДОШКОЛЬНОГО И ШКОЛЬНОГО ОБРАЗОВАНИЯ РЕСПУБЛИКИ УЗБЕКИСТАН",
        },
        "work": {"referat": "РЕФЕРАТ", "mustaqil": "САМОСТОЯТЕЛЬНАЯ РАБОТА"},
        "topic": "Тема:",
        "done_by": "Выполнил(а):",
        "checked_by": "Проверил(а):",
        "contents": "СОДЕРЖАНИЕ",
        "intro": "ВВЕДЕНИЕ",
        "conclusion": "ЗАКЛЮЧЕНИЕ",
        "references": "СПИСОК ИСПОЛЬЗОВАННОЙ ЛИТЕРАТУРЫ",
        "chapter": "ГЛАВА {roman}.",
        "presentation": "ПРЕЗЕНТАЦИЯ",
        "thanks": "Спасибо за внимание!",
        "questions": "Есть вопросы?",
        "summary": "Заключение",
    },
    "en": {
        "ministry": {
            "otm": "MINISTRY OF HIGHER EDUCATION, SCIENCE AND INNOVATION OF THE REPUBLIC OF UZBEKISTAN",
            "college": "MINISTRY OF HIGHER EDUCATION, SCIENCE AND INNOVATION OF THE REPUBLIC OF UZBEKISTAN",
            "school": "MINISTRY OF PRESCHOOL AND SCHOOL EDUCATION OF THE REPUBLIC OF UZBEKISTAN",
        },
        "work": {"referat": "RESEARCH PAPER", "mustaqil": "INDEPENDENT WORK"},
        "topic": "Topic:",
        "done_by": "Prepared by:",
        "checked_by": "Checked by:",
        "contents": "CONTENTS",
        "intro": "INTRODUCTION",
        "conclusion": "CONCLUSION",
        "references": "REFERENCES",
        "chapter": "CHAPTER {roman}.",
        "presentation": "PRESENTATION",
        "thanks": "Thank you for your attention!",
        "questions": "Any questions?",
        "summary": "Summary",
    },
}


def labels(language: str) -> dict:
    return DOC_LABELS.get(language, DOC_LABELS["uz"])


def chapter_label(language: str, index: int) -> str:
    roman = ROMAN[index] if index < len(ROMAN) else str(index + 1)
    return labels(language)["chapter"].format(roman=roman)

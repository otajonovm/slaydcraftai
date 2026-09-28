import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable

from google import genai
from google.genai import errors, types

from services.schemas import (
    LAYOUT_TYPES,
    PresentationContent,
    ReferatChapter,
    ReferatContent,
    ReferatSection,
    Slide,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], Awaitable[None]]

LANGUAGE_NAMES = {
    "uz": "Uzbek (Latin script, modern literary O'zbek tili, use ' for o' and g')",
    "ru": "Russian",
    "en": "English",
}

SYSTEM_INSTRUCTION = (
    "You are SlideCraft AI, an expert academic writer and presentation designer. "
    "You always answer with valid JSON that strictly follows the provided schema. "
    "Never use Markdown syntax (no **, #, backticks) inside JSON string values. "
    "Content must be factual, well-structured, up to date and written in the requested language only."
)

_STR = {"type": "STRING"}
_STR_LIST = {"type": "ARRAY", "items": {"type": "STRING"}}

PRESENTATION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "presentation_title": _STR,
        "slides": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "slide_number": {"type": "INTEGER"},
                    "layout_type": {"type": "STRING", "enum": list(LAYOUT_TYPES)},
                    "title": _STR,
                    "subtitle": _STR,
                    "bullet_points": _STR_LIST,
                    "left_title": _STR,
                    "right_title": _STR,
                    "left_points": _STR_LIST,
                    "right_points": _STR_LIST,
                    "quote": _STR,
                    "quote_author": _STR,
                    "speaker_notes": _STR,
                },
                "required": ["slide_number", "layout_type", "title", "bullet_points", "speaker_notes"],
            },
        },
    },
    "required": ["presentation_title", "slides"],
}

REFERAT_OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "title": _STR,
        "chapters": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"title": _STR, "sections": _STR_LIST},
                "required": ["title", "sections"],
            },
        },
        "references": _STR_LIST,
    },
    "required": ["title", "chapters", "references"],
}

PARAGRAPHS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {"paragraphs": _STR_LIST},
    "required": ["paragraphs"],
}

REFERAT_SIZES = {
    # sections per chapter, words for intro, words per section, words for conclusion
    "short": {"sections": 2, "intro": 160, "section": 180, "conclusion": 140, "refs": 6},
    "standard": {"sections": 3, "intro": 300, "section": 380, "conclusion": 260, "refs": 10},
}


class GeminiError(Exception):
    """Raised when Gemini could not produce a usable answer."""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"^\s*#{1,6}\s*", "", text)
    text = re.sub(r"^\s*[-•●▪]\s+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [t for t in (_clean_text(v) for v in values) if t]


def _strip_numbering(title: str) -> str:
    title = _clean_text(title)
    title = re.sub(
        r"^\s*((\d+(\.\d+)*\.?)|([IVX]+\s*(BOB|БОБ|ГЛАВА|CHAPTER)?\.?)|((BOB|ГЛАВА|CHAPTER)\s*[IVX\d]+\.?))[\s:.\-–]*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return title.strip() or _clean_text(title)


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    data = json.loads(text)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("JSON root is not an object")
    return data


class GeminiService:
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: tuple[str, ...] = (),
        timeout: float = 150.0,
        max_parallel_requests: int = 4,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
        self._models = [model] + [m for m in fallback_models if m and m != model]
        self._timeout = timeout
        self._parallel = asyncio.Semaphore(max_parallel_requests)
        self.last_model = self._models[0]

    def _config(self, model: str, schema: dict[str, Any], temperature: float) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {
            "system_instruction": SYSTEM_INSTRUCTION,
            "response_mime_type": "application/json",
            "response_schema": schema,
            "temperature": temperature,
            "max_output_tokens": 16384,
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        if "2.5-flash" in model:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        elif re.search(r"gemini-[3-9]", model):
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        return types.GenerateContentConfig(**kwargs)

    async def _generate_json(
        self, prompt: str, schema: dict[str, Any], temperature: float = 0.7
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        async with self._parallel:
            for model in self._models:
                for attempt in range(3):
                    try:
                        response = await asyncio.wait_for(
                            self._client.aio.models.generate_content(
                                model=model,
                                contents=prompt,
                                config=self._config(model, schema, temperature),
                            ),
                            timeout=self._timeout,
                        )
                        text = response.text
                        if not text:
                            raise ValueError("Empty response from Gemini")
                        data = _parse_json(text)
                        self.last_model = model
                        return data
                    except errors.ClientError as exc:
                        last_error = exc
                        code = getattr(exc, "code", None)
                        logger.warning("Gemini client error (model=%s, code=%s): %s", model, code, exc)
                        if code == 429:
                            await asyncio.sleep(4 * (attempt + 1))
                            continue
                        if code in (401, 403):
                            raise GeminiError("Gemini API kaliti noto'g'ri yoki ruxsat yo'q") from exc
                        if code == 400 and "API key" in str(exc):
                            raise GeminiError("Gemini API kaliti noto'g'ri") from exc
                        break  # 404 / unsupported params -> next model
                    except errors.ServerError as exc:
                        last_error = exc
                        logger.warning("Gemini server error (model=%s): %s", model, exc)
                        await asyncio.sleep(2 * (attempt + 1))
                    except (asyncio.TimeoutError, json.JSONDecodeError, ValueError) as exc:
                        last_error = exc
                        logger.warning("Gemini bad/slow response (model=%s, attempt=%s): %r", model, attempt, exc)
                        await asyncio.sleep(1)
        raise GeminiError(f"Gemini javob bermadi: {last_error!r}")

    async def check(self) -> str:
        """Lightweight connectivity check, returns the model that answered."""
        data = await self._generate_json(
            'Return {"paragraphs": ["ok"]}', PARAGRAPHS_SCHEMA, temperature=0.0
        )
        if not data.get("paragraphs"):
            raise GeminiError("Unexpected check response")
        return self.last_model

    # ------------------------------------------------------------------ slides

    async def generate_presentation(self, topic: str, slide_count: int, language: str) -> PresentationContent:
        lang = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["uz"])
        prompt = f"""
Create a professional presentation.

Topic: "{topic}"
Language of ALL text: {lang}
Exact number of slides: {slide_count}

Rules:
- Slide 1 must have layout_type "title": title = catchy presentation title, subtitle = one-line description.
- The last slide must have layout_type "summary": title like "Conclusion", bullet_points = 3-5 key takeaways.
- Middle slides mostly use "bullet_points" with 3-5 concise facts each (max ~15 words per point, no full stops needed).
- Include exactly one "comparison" slide (fill left_title, right_title, left_points, right_points with 3-4 items each)
  and exactly one "quote" slide (fill quote with a real, well-known relevant quote and quote_author) when the slide count is 8 or more.
- For bullet_points slides you may add a short subtitle (max 10 words).
- Every slide title must be short (max 7 words) and unique.
- speaker_notes: 2-4 sentences the presenter can say, adding details not present on the slide.
- Build a logical story: introduction -> history/background -> key concepts -> examples/data -> challenges -> future -> conclusion.
- slide_number goes from 1 to {slide_count}.
""".strip()
        data = await self._generate_json(prompt, PRESENTATION_SCHEMA, temperature=0.8)
        return self._normalize_presentation(data, topic, slide_count, language)

    @staticmethod
    def _normalize_presentation(
        data: dict[str, Any], topic: str, slide_count: int, language: str
    ) -> PresentationContent:
        raw_slides = data.get("slides") or []
        slides: list[Slide] = []
        for raw in raw_slides:
            if not isinstance(raw, dict):
                continue
            layout = str(raw.get("layout_type") or "bullet_points").strip().lower()
            if layout not in LAYOUT_TYPES:
                layout = "bullet_points"
            slide = Slide(
                layout_type=layout,
                title=_clean_text(raw.get("title")),
                subtitle=_clean_text(raw.get("subtitle")),
                bullet_points=_clean_list(raw.get("bullet_points"))[:6],
                left_title=_clean_text(raw.get("left_title")),
                right_title=_clean_text(raw.get("right_title")),
                left_points=_clean_list(raw.get("left_points"))[:5],
                right_points=_clean_list(raw.get("right_points"))[:5],
                quote=_clean_text(raw.get("quote")).strip("\"'«»“”„ "),
                quote_author=_clean_text(raw.get("quote_author")).lstrip("—–- "),
                speaker_notes=_clean_text(raw.get("speaker_notes")),
            )
            if layout == "comparison" and not (slide.left_points or slide.right_points):
                half = (len(slide.bullet_points) + 1) // 2
                slide.left_points, slide.right_points = slide.bullet_points[:half], slide.bullet_points[half:]
                if not slide.left_points:
                    slide.layout_type = "bullet_points"
            if layout == "quote" and not slide.quote:
                if slide.subtitle:
                    slide.quote = slide.subtitle
                elif slide.bullet_points:
                    slide.quote = slide.bullet_points[0]
                else:
                    slide.layout_type = "bullet_points"
            if slide.layout_type == "bullet_points" and not slide.bullet_points:
                continue
            slides.append(slide)

        if len(slides) < 3:
            raise GeminiError("Gemini juda kam slayd qaytardi")

        title = _clean_text(data.get("presentation_title")) or topic
        if len(slides) > slide_count:
            slides = slides[: slide_count - 1] + [slides[-1]]

        first, last = slides[0], slides[-1]
        if first.layout_type != "title":
            slides.insert(0, Slide(layout_type="title", title=title, subtitle=topic))
            if len(slides) > slide_count:
                slides.pop(-2)
        if last.layout_type != "summary":
            last.layout_type = "summary"
            if not last.bullet_points:
                last.bullet_points = last.left_points + last.right_points or [last.quote or title]
        for middle in slides[1:-1]:
            if middle.layout_type in ("title", "summary"):
                middle.layout_type = "bullet_points"
                if not middle.bullet_points:
                    middle.bullet_points = [middle.subtitle or middle.title]
        if not slides[0].title:
            slides[0].title = title
        for index, slide in enumerate(slides, start=1):
            slide.slide_number = index
            if not slide.title:
                slide.title = title
        return PresentationContent(presentation_title=title, slides=slides, language=language)

    # ----------------------------------------------------------------- referat

    async def generate_referat(
        self,
        topic: str,
        language: str,
        size: str,
        work_type: str,
        on_progress: ProgressCallback | None = None,
    ) -> ReferatContent:
        cfg = REFERAT_SIZES.get(size, REFERAT_SIZES["standard"])
        lang = LANGUAGE_NAMES.get(language, LANGUAGE_NAMES["uz"])
        kind = "independent study work (mustaqil ish)" if work_type == "mustaqil" else "academic essay (referat)"

        outline_prompt = f"""
Plan an {kind} for a university/college student in Uzbekistan.

Topic: "{topic}"
Language of ALL text: {lang}

Return:
- title: the refined topic title.
- chapters: exactly 2 chapters. Each chapter has a title and exactly {cfg['sections']} section titles
  (chapter 1 = theoretical foundations, chapter 2 = practical/analytical aspects, modern state, perspectives).
  Do NOT put numbering like "1.1" or "I BOB" in titles.
- references: {cfg['refs']} real, relevant, recent (preferably 2015-2025) literature sources formatted in academic
  style (Author A.A. Title. - City: Publisher, Year. - pages.), include laws/decrees of the Republic of Uzbekistan
  when relevant and 1-2 reliable web resources at the end. No numbering.
""".strip()
        outline = await self._generate_json(outline_prompt, REFERAT_OUTLINE_SCHEMA, temperature=0.6)

        title = _clean_text(outline.get("title")) or topic
        chapters: list[ReferatChapter] = []
        for raw in (outline.get("chapters") or [])[:3]:
            if not isinstance(raw, dict):
                continue
            sections = [_strip_numbering(s) for s in _clean_list(raw.get("sections"))][: cfg["sections"] + 1]
            sections = [s for s in sections if s]
            chapter_title = _strip_numbering(raw.get("title") or "")
            if chapter_title and sections:
                chapters.append(ReferatChapter(title=chapter_title, sections=[ReferatSection(title=s) for s in sections]))
        if len(chapters) < 2:
            raise GeminiError("Referat rejasi to'liq tuzilmadi")
        references = [re.sub(r"^\s*\d+[.)]\s*", "", r) for r in _clean_list(outline.get("references"))]

        plan_lines = []
        for ci, chapter in enumerate(chapters, start=1):
            plan_lines.append(f"Chapter {ci}. {chapter.title}")
            for si, section in enumerate(chapter.sections, start=1):
                plan_lines.append(f"  {ci}.{si}. {section.title}")
        plan_text = "\n".join(plan_lines)

        def part_prompt(part: str, words: int, extra: str) -> str:
            return f"""
You are writing one part of an {kind}.
Topic: "{title}"
Language of ALL text: {lang}
Full plan of the work:
{plan_text}

Write ONLY this part: {part}
Target length: about {words} words, split into 3-6 coherent paragraphs.
{extra}
Requirements: formal academic style, concrete facts, examples, figures and dates where appropriate,
references to Uzbekistan's context when relevant. Do not repeat the part title, no headings, no lists,
no Markdown, no references section. Return paragraphs as separate strings.
""".strip()

        jobs: list[tuple[str, tuple[int, int] | None, str]] = [
            (
                part_prompt(
                    "INTRODUCTION",
                    cfg["intro"],
                    "Cover: relevance of the topic, goal and objectives of the work, object and subject, structure of the work.",
                ),
                None,
                "intro",
            )
        ]
        for ci, chapter in enumerate(chapters):
            for si, section in enumerate(chapter.sections):
                jobs.append(
                    (
                        part_prompt(
                            f'section {ci + 1}.{si + 1} "{section.title}" of chapter {ci + 1} "{chapter.title}"',
                            cfg["section"],
                            "Focus strictly on this section; do not cover other sections of the plan.",
                        ),
                        (ci, si),
                        "section",
                    )
                )
        jobs.append(
            (
                part_prompt(
                    "CONCLUSION",
                    cfg["conclusion"],
                    "Summarize the main results of every chapter, give practical recommendations and conclusions.",
                ),
                None,
                "conclusion",
            )
        )

        total = len(jobs)
        done = 0
        lock = asyncio.Lock()

        async def run(prompt: str) -> list[str]:
            nonlocal done
            data = await self._generate_json(prompt, PARAGRAPHS_SCHEMA, temperature=0.7)
            paragraphs = _clean_list(data.get("paragraphs"))
            if not paragraphs:
                raise GeminiError("Bo'sh bo'lim qaytdi")
            async with lock:
                done += 1
                current = done
            if on_progress is not None:
                try:
                    await on_progress(current, total)
                except Exception:  # progress UI must never break generation
                    logger.debug("progress callback failed", exc_info=True)
            return paragraphs

        results = await asyncio.gather(*(run(prompt) for prompt, _, _ in jobs))

        content = ReferatContent(title=title, chapters=chapters, references=references)
        for (_, position, kind_name), paragraphs in zip(jobs, results):
            if kind_name == "intro":
                content.introduction = paragraphs
            elif kind_name == "conclusion":
                content.conclusion = paragraphs
            elif position is not None:
                ci, si = position
                content.chapters[ci].sections[si].paragraphs = paragraphs
        return content

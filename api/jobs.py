"""Background document generation for the Mini App.

A job lives in memory while it runs (for live progress) and is persisted in the `generations`
and `generated_files` tables. Finished files are also sent to the user's Telegram chat: the
returned file_id keeps them downloadable after the dyno's ephemeral disk is wiped.
"""

import asyncio
import datetime as dt
import logging
import math
import shutil
import time
import uuid
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from bot.utils import ACTIVE_JOBS, JOB_SEMAPHORE, job_workspace, safe_filename
from config import settings
from database import Database, GeneratedFile
from services.docx_generator import build_referat
from services.gemini_service import GeminiError, GeminiService
from services.pdf_converter import PdfConverter
from services.pptx_generator import build_presentation
from services.schemas import ReferatMeta

logger = logging.getLogger(__name__)

# Progress window (percent) of every stage; progress eases towards the upper bound while a stage runs.
STAGE_RANGES: dict[str, tuple[float, float]] = {
    "queued": (2, 5),
    "outline": (5, 18),
    "writing": (18, 78),
    "rendering": (80, 96),
    "done": (100, 100),
}
FINISHED_JOB_TTL = 15 * 60
FILE_CACHE_TTL = 24 * 3600

AI_ERROR = "AI xizmati hozir javob bera olmadi. Birozdan so'ng qayta urinib ko'ring."
GENERIC_ERROR = "Kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring."


@dataclass
class Job:
    id: int
    user_id: int
    doc_type: str
    topic: str
    is_free: bool
    status: str = "running"  # running, completed, failed
    stage: str = "queued"
    stage_started: float = field(default_factory=time.monotonic)
    floor: float = 0.0
    files: list[GeneratedFile] = field(default_factory=list)
    error: str | None = None
    finished_at: float | None = None

    def set_stage(self, stage: str) -> None:
        if stage != self.stage:
            self.stage = stage
            self.stage_started = time.monotonic()
            self.floor = 0.0

    @property
    def progress(self) -> int:
        if self.status == "completed":
            return 100
        lo, hi = STAGE_RANGES[self.stage]
        elapsed = time.monotonic() - self.stage_started
        eased = lo + (hi - lo) * (1 - math.exp(-elapsed / 25))
        return int(min(hi, max(eased, self.floor)))


def cache_path(file_id: str, name: str) -> Path:
    return settings.files_dir / file_id / name


class JobManager:
    def __init__(self, bot: Bot, db: Database, gemini: GeminiService, pdf: PdfConverter) -> None:
        self.bot = bot
        self.db = db
        self.gemini = gemini
        self.pdf = pdf
        self._jobs: dict[int, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- public

    def get(self, job_id: int) -> Job | None:
        self._forget_old()
        return self._jobs.get(job_id)

    async def start(self, user_id: int, request: dict[str, Any], is_free: bool) -> Job:
        """Caller must have checked the balance and that the user has no active job."""
        doc_type = request["type"]
        ACTIVE_JOBS.add(user_id)
        try:
            generation_id = await self.db.create_generation(
                user_id, doc_type, request["topic"], dict(request, source_app="miniapp"), is_free
            )
        except Exception:
            ACTIVE_JOBS.discard(user_id)
            raise
        job = Job(id=generation_id, user_id=user_id, doc_type=doc_type, topic=request["topic"], is_free=is_free)
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, request), name=f"miniapp-job-{job.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def cleanup_cache_forever(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._cleanup_cache)
            except Exception:
                logger.exception("File cache cleanup failed")
            await asyncio.sleep(3600)

    # ---------------------------------------------------------------- internals

    def _forget_old(self) -> None:
        now = time.monotonic()
        for job_id in [j.id for j in self._jobs.values() if j.finished_at and now - j.finished_at > FINISHED_JOB_TTL]:
            self._jobs.pop(job_id, None)

    @staticmethod
    def _cleanup_cache() -> None:
        cutoff = time.time() - FILE_CACHE_TTL
        for entry in settings.files_dir.iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)

    async def _stage_later(self, job: Job, delay: float, stage: str) -> None:
        await asyncio.sleep(delay)
        if job.status == "running" and STAGE_RANGES[job.stage][0] < STAGE_RANGES[stage][0]:
            job.set_stage(stage)

    async def _run(self, job: Job, req: dict[str, Any]) -> None:
        watermark = settings.watermark_text if job.is_free else None
        try:
            async with JOB_SEMAPHORE, job_workspace() as workdir:
                job.set_stage("outline")
                source = req["type"] if req["type"] != "pdf" else req["source"]
                if source == "presentation":
                    title, outputs = await self._presentation(job, req, workdir, watermark)
                else:
                    title, outputs = await self._referat(job, req, workdir, watermark)
                if req["type"] == "pdf":
                    outputs = [p for p in outputs if p.suffix == ".pdf"]
                if not outputs:
                    raise RuntimeError("no output files")
                await self._store(job, title, outputs)

            await self.db.finish_generation(job.id, success=True)
            spent = await self.db.deduct_credit(job.user_id, use_free=job.is_free, generation_id=job.id)
            if spent is None:
                logger.warning("No credit could be deducted for user=%s generation=%s", job.user_id, job.id)
            job.set_stage("done")
            job.status = "completed"
        except asyncio.CancelledError:
            job.status, job.error = "failed", "Server qayta ishga tushdi. Iltimos, qayta urinib ko'ring."
            await self._safe_finish(job, "cancelled")
            raise
        except GeminiError as exc:
            logger.warning("Mini App job %s failed (Gemini): %s", job.id, exc)
            job.status, job.error = "failed", AI_ERROR
            await self._safe_finish(job, str(exc))
        except Exception as exc:
            logger.exception("Mini App job %s failed", job.id)
            job.status, job.error = "failed", GENERIC_ERROR
            await self._safe_finish(job, repr(exc))
        finally:
            job.finished_at = time.monotonic()
            ACTIVE_JOBS.discard(job.user_id)

    async def _safe_finish(self, job: Job, error: str) -> None:
        try:
            await self.db.finish_generation(job.id, success=False, error=error)
        except Exception:
            logger.exception("Cannot mark generation %s as failed", job.id)

    async def _presentation(
        self, job: Job, req: dict[str, Any], workdir: Path, watermark: str | None
    ) -> tuple[str, list[Path]]:
        switcher = asyncio.create_task(self._stage_later(job, 5, "writing"))
        try:
            content = await self.gemini.generate_presentation(req["topic"], req["slides"], req["language"])
        finally:
            switcher.cancel()
        job.set_stage("rendering")
        base = safe_filename(content.presentation_title or req["topic"])
        pptx = await asyncio.to_thread(build_presentation, content, req["theme"], workdir / f"{base}.pptx", watermark)
        pdf = await self.pdf.presentation_to_pdf(pptx, content, req["theme"], watermark)
        return content.presentation_title or req["topic"], [p for p in (pptx, pdf) if p]

    async def _referat(
        self, job: Job, req: dict[str, Any], workdir: Path, watermark: str | None
    ) -> tuple[str, list[Path]]:
        async def on_progress(done: int, total: int) -> None:
            job.set_stage("writing")
            lo, hi = STAGE_RANGES["writing"]
            job.floor = lo + (hi - lo) * done / max(total, 1)

        content = await self.gemini.generate_referat(
            req["topic"], req["language"], req["size"], req["work_type"], on_progress=on_progress
        )
        job.set_stage("rendering")
        meta = ReferatMeta(
            work_type=req["work_type"],
            institution_type=req["institution_type"],
            institution=req["institution"],
            student=req["student"],
            teacher=req["teacher"],
            city=req["city"],
            year=dt.date.today().year,
            language=req["language"],
        )
        base = safe_filename(content.title or req["topic"])
        docx = await asyncio.to_thread(build_referat, content, meta, workdir / f"{base}.docx", watermark)
        pdf = await self.pdf.referat_to_pdf(docx, content, meta, watermark)
        return content.title or req["topic"], [p for p in (docx, pdf) if p]

    async def _store(self, job: Job, title: str, outputs: list[Path]) -> None:
        for index, path in enumerate(outputs):
            file_id = uuid.uuid4().hex
            target = cache_path(file_id, path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(path), target)

            caption = (
                f"📱 <b>{escape(title)}</b>\nMini App orqali tayyorlandi" if index == 0 else "🖨 PDF versiya"
            )
            tg_file_id = None
            try:
                sent = await self.bot.send_document(
                    job.user_id,
                    FSInputFile(target, filename=path.name),
                    caption=caption,
                    disable_notification=True,
                )
                tg_file_id = sent.document.file_id if sent.document else None
            except TelegramAPIError as exc:
                logger.warning("Cannot send Mini App file to %s: %s", job.user_id, exc)

            row = await self.db.add_generated_file(
                file_id, job.id, job.user_id, path.name, path.suffix.lstrip(".").lower(),
                target.stat().st_size, tg_file_id,
            )
            job.files.append(row)

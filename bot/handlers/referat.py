import asyncio
import datetime as dt
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.keyboards.inline import (
    INSTITUTION_TYPES,
    LANGUAGES,
    REFERAT_SIZES,
    WORK_TYPES,
    city_kb,
    confirm_kb,
    institution_type_kb,
    language_kb,
    referat_size_kb,
    skip_kb,
    work_type_kb,
)
from bot.keyboards.reply import BTN_REFERAT, cancel_kb, main_menu_kb
from bot.states import ReferatStates
from bot.middlewares import REQUIRES_CREDIT
from bot.utils import (
    ACTIVE_JOBS,
    JOB_SEMAPHORE,
    UserText,
    job_workspace,
    safe_edit,
    safe_filename,
    send_charge_report,
)
from config import settings
from database import Database, UserBalance
from services.docx_generator import build_referat
from services.gemini_service import GeminiError, GeminiService
from services.pdf_converter import PdfConverter
from services.schemas import ReferatMeta

logger = logging.getLogger(__name__)
router = Router(name="referat")

TOPIC_MIN, TOPIC_MAX = 3, 300
NAME_MAX = 120


def _summary(data: dict) -> str:
    return (
        "📋 <b>Referat parametrlari</b>\n\n"
        f"📌 Mavzu: <b>{escape(data['topic'])}</b>\n"
        f"📄 Turi: <b>{WORK_TYPES[data['work_type']]}</b>\n"
        f"🏛 Muassasa: <b>{escape(data.get('institution') or '—')}</b> ({INSTITUTION_TYPES[data['institution_type']]})\n"
        f"👨‍🎓 Bajardi: <b>{escape(data.get('student') or '—')}</b>\n"
        f"👨‍🏫 Qabul qildi: <b>{escape(data.get('teacher') or '—')}</b>\n"
        f"📍 Shahar: <b>{escape(data['city'])}</b>\n"
        f"📚 Hajm: <b>{REFERAT_SIZES[data['size']]}</b>\n"
        f"🌐 Til: <b>{LANGUAGES[data['language']]}</b>\n\n"
        "Hammasi to'g'rimi?"
    )


def _clean(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------------------ steps


@router.message(Command("referat"), flags=REQUIRES_CREDIT)
@router.message(F.text == BTN_REFERAT, flags=REQUIRES_CREDIT)
async def start_referat(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ReferatStates.topic)
    await message.answer(
        "📝 <b>Yangi referat / mustaqil ish</b>\n\n"
        "Ish <b>mavzusini</b> yozing.\n"
        "<i>Masalan: O'zbekistonda raqamli iqtisodiyotning rivojlanishi</i>",
        reply_markup=cancel_kb(),
    )


@router.message(ReferatStates.topic, UserText())
async def got_topic(message: Message, state: FSMContext) -> None:
    topic = _clean(message.text)
    if not TOPIC_MIN <= len(topic) <= TOPIC_MAX:
        await message.answer(f"Mavzu {TOPIC_MIN}–{TOPIC_MAX} belgi oralig'ida bo'lishi kerak. Qaytadan yozing:")
        return
    await state.update_data(topic=topic)
    await state.set_state(ReferatStates.work_type)
    await message.answer(f"✅ Mavzu: <b>{escape(topic)}</b>\n\n📄 Ish turini tanlang:", reply_markup=work_type_kb())


@router.callback_query(ReferatStates.work_type, F.data.startswith("r:work:"))
async def got_work_type(callback: CallbackQuery, state: FSMContext) -> None:
    work_type = callback.data.rsplit(":", 1)[1]
    if work_type not in WORK_TYPES:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(work_type=work_type)
    await state.set_state(ReferatStates.institution_type)
    await callback.answer()
    await safe_edit(callback.message, f"✅ Turi: <b>{WORK_TYPES[work_type]}</b>\n\n🏛 Ta'lim muassasasi turini tanlang:",
                    reply_markup=institution_type_kb())


@router.callback_query(ReferatStates.institution_type, F.data.startswith("r:inst:"))
async def got_institution_type(callback: CallbackQuery, state: FSMContext) -> None:
    inst_type = callback.data.rsplit(":", 1)[1]
    if inst_type not in INSTITUTION_TYPES:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(institution_type=inst_type)
    await state.set_state(ReferatStates.institution_name)
    await callback.answer()
    await safe_edit(
        callback.message,
        f"✅ Muassasa turi: <b>{INSTITUTION_TYPES[inst_type]}</b>\n\n"
        "🏛 Muassasa <b>to'liq nomini</b> yozing.\n"
        "<i>Masalan: Toshkent davlat iqtisodiyot universiteti</i>",
        reply_markup=skip_kb("institution"),
    )


@router.message(ReferatStates.institution_name, UserText())
async def got_institution_name(message: Message, state: FSMContext) -> None:
    name = _clean(message.text)[:200]
    await state.update_data(institution=name)
    await _ask_student(message, state)


async def _ask_student(message: Message, state: FSMContext) -> None:
    await state.set_state(ReferatStates.student)
    await message.answer(
        "👨‍🎓 <b>Talaba</b> F.I.Sh. ni yozing (titul varag'idagi «Bajardi» qismi uchun).\n"
        "<i>Masalan: Aliyev Vali, 2-kurs, 205-guruh</i>",
        reply_markup=skip_kb("student"),
    )


@router.message(ReferatStates.student, UserText())
async def got_student(message: Message, state: FSMContext) -> None:
    await state.update_data(student=_clean(message.text)[:NAME_MAX])
    await _ask_teacher(message, state)


async def _ask_teacher(message: Message, state: FSMContext) -> None:
    await state.set_state(ReferatStates.teacher)
    await message.answer(
        "👨‍🏫 <b>O'qituvchi</b> F.I.Sh. ni yozing («Qabul qildi» qismi uchun).",
        reply_markup=skip_kb("teacher"),
    )


@router.message(ReferatStates.teacher, UserText())
async def got_teacher(message: Message, state: FSMContext) -> None:
    await state.update_data(teacher=_clean(message.text)[:NAME_MAX])
    await _ask_city(message, state)


async def _ask_city(message: Message, state: FSMContext) -> None:
    await state.set_state(ReferatStates.city)
    await message.answer(
        "📍 Shaharni tanlang yoki o'zingiz yozing (titul varag'ining pastida yoziladi):",
        reply_markup=city_kb(),
    )


@router.message(ReferatStates.city, UserText())
async def got_city_text(message: Message, state: FSMContext) -> None:
    await state.update_data(city=_clean(message.text)[:60])
    await _ask_size(message, state)


@router.callback_query(ReferatStates.city, F.data.startswith("r:city:"))
async def got_city_button(callback: CallbackQuery, state: FSMContext) -> None:
    city = callback.data.split(":", 2)[2]
    await state.update_data(city=city)
    await callback.answer()
    await safe_edit(callback.message, f"✅ Shahar: <b>{escape(city)}</b>")
    await _ask_size(callback.message, state)


async def _ask_size(message: Message, state: FSMContext) -> None:
    await state.set_state(ReferatStates.size)
    await message.answer("📚 Ish hajmini tanlang:", reply_markup=referat_size_kb())


@router.callback_query(F.data.startswith("r:skip:"))
async def skip_field(callback: CallbackQuery, state: FSMContext) -> None:
    field = callback.data.rsplit(":", 1)[1]
    current = await state.get_state()
    expected = {
        "institution": ReferatStates.institution_name.state,
        "student": ReferatStates.student.state,
        "teacher": ReferatStates.teacher.state,
    }
    if expected.get(field) != current:
        await callback.answer("Bu tugma eskirgan.", show_alert=True)
        return
    await state.update_data(**{field: ""})
    await callback.answer("O'tkazib yuborildi")
    await safe_edit(callback.message, "⏭ O'tkazib yuborildi.")
    if field == "institution":
        await _ask_student(callback.message, state)
    elif field == "student":
        await _ask_teacher(callback.message, state)
    else:
        await _ask_city(callback.message, state)


@router.callback_query(ReferatStates.size, F.data.startswith("r:size:"))
async def got_size(callback: CallbackQuery, state: FSMContext) -> None:
    size = callback.data.rsplit(":", 1)[1]
    if size not in REFERAT_SIZES:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(size=size)
    await state.set_state(ReferatStates.language)
    await callback.answer()
    await safe_edit(callback.message, f"✅ Hajm: <b>{REFERAT_SIZES[size]}</b>\n\n🌐 Ish tilini tanlang:",
                    reply_markup=language_kb("r"))


@router.callback_query(ReferatStates.language, F.data.startswith("r:lang:"))
async def got_language(callback: CallbackQuery, state: FSMContext) -> None:
    language = callback.data.rsplit(":", 1)[1]
    if language not in LANGUAGES:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(language=language)
    await state.set_state(ReferatStates.confirm)
    await callback.answer()
    await safe_edit(callback.message, _summary(await state.get_data()), reply_markup=confirm_kb("r"))


@router.message(
    ReferatStates.topic,
    ReferatStates.institution_name,
    ReferatStates.student,
    ReferatStates.teacher,
    ReferatStates.city,
)
async def bad_text(message: Message) -> None:
    await message.answer("Iltimos, javobni matn ko'rinishida yozing yoki tugmalardan foydalaning.")


@router.callback_query(ReferatStates.confirm, F.data == "r:restart")
async def restart(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await safe_edit(callback.message, "🔄 Qaytadan boshlaymiz.")
    await start_referat(callback.message, state)


# ------------------------------------------------------------- generation


@router.callback_query(ReferatStates.confirm, F.data == "r:go", flags=REQUIRES_CREDIT)
async def generate(
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    db: Database,
    gemini: GeminiService,
    pdf: PdfConverter,
    balance: UserBalance,
) -> None:
    user = callback.from_user
    if user.id in ACTIVE_JOBS:
        await callback.answer("⏳ Oldingi buyurtmangiz hali tayyorlanmoqda. Iltimos kuting.", show_alert=True)
        return

    data = await state.get_data()
    is_free = balance.uses_free_credit
    watermark = settings.watermark_text if is_free else None
    try:
        generation_id = await db.create_generation(user.id, "referat", data["topic"], data, is_free)
    except Exception:
        logger.exception("Cannot create generation record for %s", user.id)
        await callback.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Boshladik! 🚀")
    ACTIVE_JOBS.add(user.id)

    meta = ReferatMeta(
        work_type=data["work_type"],
        institution_type=data["institution_type"],
        institution=data.get("institution", ""),
        student=data.get("student", ""),
        teacher=data.get("teacher", ""),
        city=data.get("city") or "Toshkent",
        year=dt.date.today().year,
        language=data["language"],
    )

    chat_id = callback.message.chat.id
    status = callback.message
    header = f"📝 <b>{escape(data['topic'])}</b>\n\n"

    async def on_progress(done: int, total: int) -> None:
        filled = round(10 * done / total)
        bar = "▰" * filled + "▱" * (10 - filled)
        await safe_edit(status, header + f"✍️ Matn yozilmoqda...\n{bar} {done}/{total} bo'lim")

    try:
        if JOB_SEMAPHORE.locked():
            await safe_edit(status, header + "🕒 Navbatda turibsiz, biroz kuting...")
        async with JOB_SEMAPHORE, ChatActionSender.upload_document(bot=bot, chat_id=chat_id), job_workspace() as workdir:
            await safe_edit(status, header + "⏳ Reja tuzilmoqda...")
            content = await gemini.generate_referat(
                data["topic"], data["language"], data["size"], data["work_type"], on_progress=on_progress
            )

            await safe_edit(status, header + "🖋 Word hujjat shakllantirilmoqda...")
            base = safe_filename(content.title or data["topic"])
            docx_path = await asyncio.to_thread(build_referat, content, meta, workdir / f"{base}.docx", watermark)

            await safe_edit(status, header + "📄 PDF versiya tayyorlanmoqda...")
            pdf_path = await pdf.referat_to_pdf(docx_path, content, meta, watermark)

            await safe_edit(status, header + "📤 Fayllar yuborilmoqda...")
            sections = sum(len(ch.sections) for ch in content.chapters)
            caption = (
                f"📝 <b>{escape(content.title)}</b>\n"
                f"📚 {len(content.chapters)} bob, {sections} fasl, {len(content.references)} ta manba\n\n"
                "✏️ Tahrirlanadigan Word fayli"
            )
            await bot.send_document(chat_id, FSInputFile(docx_path, filename=docx_path.name), caption=caption)
            if pdf_path:
                await bot.send_document(
                    chat_id, FSInputFile(pdf_path, filename=pdf_path.name),
                    caption="🖨 Chop etishga tayyor PDF versiya",
                )

        await db.finish_generation(generation_id, success=True)
        await safe_edit(status, header + "✅ Referat tayyor!")
        await send_charge_report(bot, db, chat_id, user.id, generation_id, is_free)
    except GeminiError as exc:
        logger.warning("Referat generation failed (Gemini): %s", exc)
        await db.finish_generation(generation_id, success=False, error=str(exc))
        await safe_edit(status, header + "⚠️ AI xizmati hozir javob bera olmadi. Birozdan so'ng qayta urinib ko'ring.\n💳 Kredit yechilmadi.")
        await bot.send_message(chat_id, "Bosh menyu 👇", reply_markup=main_menu_kb())
    except Exception as exc:
        logger.exception("Referat generation failed")
        await db.finish_generation(generation_id, success=False, error=repr(exc))
        await safe_edit(status, header + "⚠️ Kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring.\n💳 Kredit yechilmadi.")
        await bot.send_message(chat_id, "Bosh menyu 👇", reply_markup=main_menu_kb())
    finally:
        ACTIVE_JOBS.discard(user.id)

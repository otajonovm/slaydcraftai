import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.chat_action import ChatActionSender

from bot.keyboards.inline import LANGUAGES, SLIDE_COUNTS, THEMES, confirm_kb, language_kb, slide_count_kb, theme_kb
from bot.keyboards.reply import BTN_PRESENTATION, MENU_TEXTS, cancel_kb, main_menu_kb
from bot.states import PresentationStates
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
from services.gemini_service import GeminiError, GeminiService
from services.pdf_converter import PdfConverter
from services.pptx_generator import build_presentation

logger = logging.getLogger(__name__)
router = Router(name="presentation")

TOPIC_MIN, TOPIC_MAX = 3, 300


def _summary(data: dict) -> str:
    return (
        "📋 <b>Taqdimot parametrlari</b>\n\n"
        f"📌 Mavzu: <b>{escape(data['topic'])}</b>\n"
        f"🔢 Slaydlar: <b>{data['slide_count']} ta</b>\n"
        f"🌐 Til: <b>{LANGUAGES[data['language']]}</b>\n"
        f"🎨 Dizayn: <b>{THEMES[data['theme']]}</b>\n\n"
        "Hammasi to'g'rimi?"
    )


@router.message(Command("slide"), flags=REQUIRES_CREDIT)
@router.message(F.text == BTN_PRESENTATION, flags=REQUIRES_CREDIT)
async def start_presentation(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PresentationStates.topic)
    await message.answer(
        "📊 <b>Yangi taqdimot</b>\n\n"
        "Taqdimot <b>mavzusini</b> yozing.\n"
        "<i>Masalan: Sun'iy intellektning ta'limdagi o'rni</i>",
        reply_markup=cancel_kb(),
    )


@router.message(PresentationStates.topic, UserText())
async def got_topic(message: Message, state: FSMContext) -> None:
    topic = " ".join(message.text.split())
    if not TOPIC_MIN <= len(topic) <= TOPIC_MAX:
        await message.answer(f"Mavzu {TOPIC_MIN}–{TOPIC_MAX} belgi oralig'ida bo'lishi kerak. Qaytadan yozing:")
        return
    await state.update_data(topic=topic)
    await state.set_state(PresentationStates.slide_count)
    await message.answer(
        f"✅ Mavzu: <b>{escape(topic)}</b>\n\n🔢 Nechta slayd kerak?",
        reply_markup=slide_count_kb(),
    )


@router.message(PresentationStates.topic, ~F.text.in_(MENU_TEXTS))
async def bad_topic(message: Message) -> None:
    await message.answer("Iltimos, mavzuni matn ko'rinishida yozing.")


@router.callback_query(PresentationStates.slide_count, F.data.startswith("p:count:"))
async def got_slide_count(callback: CallbackQuery, state: FSMContext) -> None:
    count = int(callback.data.rsplit(":", 1)[1])
    if count not in SLIDE_COUNTS:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(slide_count=count)
    await state.set_state(PresentationStates.language)
    await callback.answer()
    await safe_edit(callback.message, f"✅ Slaydlar: <b>{count} ta</b>\n\n🌐 Taqdimot tilini tanlang:",
                    reply_markup=language_kb("p"))


@router.callback_query(PresentationStates.language, F.data.startswith("p:lang:"))
async def got_language(callback: CallbackQuery, state: FSMContext) -> None:
    language = callback.data.rsplit(":", 1)[1]
    if language not in LANGUAGES:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(language=language)
    await state.set_state(PresentationStates.theme)
    await callback.answer()
    await safe_edit(callback.message, f"✅ Til: <b>{LANGUAGES[language]}</b>\n\n🎨 Dizayn mavzusini tanlang:",
                    reply_markup=theme_kb())


@router.callback_query(PresentationStates.theme, F.data.startswith("p:theme:"))
async def got_theme(callback: CallbackQuery, state: FSMContext) -> None:
    theme = callback.data.split(":", 2)[2]
    if theme not in THEMES:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(theme=theme)
    await state.set_state(PresentationStates.confirm)
    await callback.answer()
    await safe_edit(callback.message, _summary(await state.get_data()), reply_markup=confirm_kb("p"))


@router.callback_query(PresentationStates.confirm, F.data == "p:restart")
async def restart(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await safe_edit(callback.message, "🔄 Qaytadan boshlaymiz.")
    await start_presentation(callback.message, state)


@router.callback_query(PresentationStates.confirm, F.data == "p:go", flags=REQUIRES_CREDIT)
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
        generation_id = await db.create_generation(user.id, "presentation", data["topic"], data, is_free)
    except Exception:
        logger.exception("Cannot create generation record for %s", user.id)
        await callback.answer("⚠️ Xatolik yuz berdi, qayta urinib ko'ring.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Boshladik! 🚀")
    ACTIVE_JOBS.add(user.id)

    chat_id = callback.message.chat.id
    status = callback.message
    header = f"📊 <b>{escape(data['topic'])}</b>\n\n"
    try:
        if JOB_SEMAPHORE.locked():
            await safe_edit(status, header + "🕒 Navbatda turibsiz, biroz kuting...")
        async with JOB_SEMAPHORE, ChatActionSender.upload_document(bot=bot, chat_id=chat_id), job_workspace() as workdir:
            await safe_edit(status, header + "⏳ Slaydlar tuzilmoqda... (AI matn yozmoqda)")
            content = await gemini.generate_presentation(data["topic"], data["slide_count"], data["language"])

            await safe_edit(status, header + "🎨 Dizayn shakllantirilmoqda...")
            base = safe_filename(content.presentation_title or data["topic"])
            pptx_path = await asyncio.to_thread(
                build_presentation, content, data["theme"], workdir / f"{base}.pptx", watermark
            )

            await safe_edit(status, header + "📄 PDF versiya tayyorlanmoqda...")
            pdf_path = await pdf.presentation_to_pdf(pptx_path, content, data["theme"], watermark)

            await safe_edit(status, header + "📤 Fayllar yuborilmoqda...")
            caption = (
                f"📊 <b>{escape(content.presentation_title)}</b>\n"
                f"🔢 {len(content.slides)} ta slayd • {THEMES[data['theme']]}\n\n"
                "✏️ Tahrirlanadigan PowerPoint fayli (ma'ruzachi izohlari bilan)"
            )
            await bot.send_document(chat_id, FSInputFile(pptx_path, filename=pptx_path.name), caption=caption)
            if pdf_path:
                await bot.send_document(
                    chat_id, FSInputFile(pdf_path, filename=pdf_path.name),
                    caption="🖨 Chop etishga tayyor PDF versiya",
                )

        await db.finish_generation(generation_id, success=True)
        await safe_edit(status, header + "✅ Taqdimot tayyor!")
        await send_charge_report(bot, db, chat_id, user.id, generation_id, is_free)
    except GeminiError as exc:
        logger.warning("Presentation generation failed (Gemini): %s", exc)
        await db.finish_generation(generation_id, success=False, error=str(exc))
        await safe_edit(status, header + "⚠️ AI xizmati hozir javob bera olmadi. Birozdan so'ng qayta urinib ko'ring.\n💳 Kredit yechilmadi.")
        await bot.send_message(chat_id, "Bosh menyu 👇", reply_markup=main_menu_kb())
    except Exception as exc:
        logger.exception("Presentation generation failed")
        await db.finish_generation(generation_id, success=False, error=repr(exc))
        await safe_edit(status, header + "⚠️ Kutilmagan xatolik yuz berdi. Iltimos, qayta urinib ko'ring.\n💳 Kredit yechilmadi.")
        await bot.send_message(chat_id, "Bosh menyu 👇", reply_markup=main_menu_kb())
    finally:
        ACTIVE_JOBS.discard(user.id)

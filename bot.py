remove(path)

                except Exception:

                    pass

# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram error: %s",
        context.error
    )

# =========================================================
# CREATE TELEGRAM APP
# =========================================================

def create_application():

    application = (
        ApplicationBuilder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        MessageHandler(
            filters.AUDIO
            |
            filters.VOICE,
            handle_audio
        )
    )

    application.add_error_handler(
        error_handler
    )

    return application

# =========================================================
# MAIN
# =========================================================

def main():

    # Flask runs in background.
    # Telegram MUST remain in main thread.

    start_web_server()

    application = (
        create_application()
    )

    logger.info(
        "========================================"
    )

    logger.info(
        "🤖 Telegram Recap Bot Started"
    )

    logger.info(
        "Gemini Model: %s",
        GEMINI_MODEL
    )

    logger.info(
        "TTS Server: %s",
        TTS_URL
    )

    logger.info(
        "========================================"
    )

    # IMPORTANT:
    # stop_signals=None prevents the
    # set_wakeup_fd main-thread error
    # when deployed through a threaded
    # environment.

    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )

# =========================================================
# RUN
# =========================================================

if name == "__main__":

    main()

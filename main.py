"""TPrints — chek print xizmati.

Ishga tushirish:  python main.py            (oyna bilan)
                  python main.py --minimized (yashirin, trayda)
"""
import ctypes
import sys

from app import APP_NAME
from app.config import Config
from app.logger import setup_logger

MUTEX_NAME = "Global\\TPrints_SingleInstance_Mutex"


def _single_instance() -> bool:
    """Dastur ikkinchi marta ochilishining oldini oladi."""
    try:
        import win32api
        import win32event
        import winerror
        _single_instance.handle = win32event.CreateMutex(None, False, MUTEX_NAME)
        return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _enable_dpi_awareness():
    """UI Windows'da xira ko'rinmasligi uchun."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _enable_dpi_awareness()

    if not _single_instance():
        ctypes.windll.user32.MessageBoxW(
            0, f"{APP_NAME} allaqachon ishlamoqda.\n"
               f"Tizim tray'idagi (soat yonidagi) belgini tekshiring.",
            APP_NAME, 0x40)
        sys.exit(0)

    config = Config()
    logger = setup_logger()
    logger.info("%s ishga tushmoqda...", APP_NAME)

    from app.jobs import JobQueue
    from app.printing.manager import PrintManager
    from app.server import ServerThread, create_app
    from app.ui.main_window import MainWindow
    from app.ui.tray import Tray

    manager = PrintManager(config, logger)
    job_queue = JobQueue(manager, config, logger)

    flask_app = create_app(config, job_queue, manager, logger)
    server = ServerThread(flask_app, config.get("host"), int(config.get("port")),
                          logger)
    try:
        server.start()
    except OSError as e:
        ctypes.windll.user32.MessageBoxW(
            0, f"Server ishga tushmadi:\n{e}\n\n"
               f"Sozlamalardan boshqa port tanlashingiz mumkin "
               f"(oyna baribir ochiladi).",
            APP_NAME, 0x30)

    tray = Tray()
    tray.start()

    start_minimized = ("--minimized" in sys.argv or
                       bool(config.get("start_minimized")))
    window = MainWindow(config, job_queue, manager, tray, server, logger)
    window.run(start_minimized=start_minimized)


if __name__ == "__main__":
    main()

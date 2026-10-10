"""Local notifications.

Desktop / Android builds: `plyer` posts a native notification. On Android, native notifications
are automatically mirrored to a paired smartwatch (Wear OS / Galaxy Watch) by the OS, so no
separate watch code is needed for basic alerts. A dedicated watch UI would need native code.
"""
from __future__ import annotations


def notify(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="BladderSense", timeout=10)
    except Exception as e:  # plyer missing / unsupported platform
        print(f"[notify fallback] {title}: {message} ({e})")

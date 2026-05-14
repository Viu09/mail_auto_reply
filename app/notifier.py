from __future__ import annotations

try:
    from plyer import notification
except Exception:
    notification = None


class Notifier:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled and notification is not None

    def notify(self, title: str, message: str) -> None:
        if not self.enabled:
            return

        try:
            notification.notify(
                title=title[:64],
                message=message[:256],
                app_name="Gmail AI Assistant",
                timeout=10,
            )
        except Exception as exc:
            print(f"Notification desktop ignoree: {exc}")

from dataclasses import dataclass


@dataclass(frozen=True)
class Package:
    key: str
    title: str
    credits: int
    price: int
    emoji: str
    note: str = ""

    @property
    def unit_price(self) -> int:
        return round(self.price / self.credits)


PACKAGES: dict[str, Package] = {
    "single": Package("single", "1 ta generatsiya", 1, 5_000, "1️⃣"),
    "student": Package("student", "\"Talaba\" to'plami", 5, 15_000, "📦", "40% chegirma!"),
    "session": Package("session", "\"Sessiya\" to'plami", 15, 35_000, "🔥", "1 tasi ~2 300 so'm"),
    "pro": Package("pro", "\"Pro\" to'plami", 50, 69_000, "💎", "1 tasi ~1 400 so'm"),
}


def fmt_uzs(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def get_package(key: str) -> Package | None:
    return PACKAGES.get(key)

"""Load demo data, with dates relative to today, so the app has something to show."""

from datetime import date, timedelta

from . import core
from .db import session


def _d(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


DEMO_DOCUMENTS = [
    {"kind": "invoice", "title": "LG split AC invoice", "vendor": "Reliance Digital", "item_name": "LG 1.5 ton split AC",
     "amount": 38990, "doc_date": _d(-345), "warranty_months": 12, "contact_email": "service@example-lg.in",
     "notes": "AC bought with a 1-year comprehensive warranty."},
    {"kind": "invoice", "title": "Samsung refrigerator invoice", "vendor": "Croma", "item_name": "Samsung 253 L refrigerator",
     "amount": 27490, "doc_date": _d(-200), "warranty_months": 12, "contact_email": "support@example-samsung.in"},
    {"kind": "bill", "title": "BESCOM electricity bill", "vendor": "BESCOM", "category": "electricity",
     "amount": 1420, "doc_date": _d(-95), "expiry_date": _d(-80)},
    {"kind": "bill", "title": "BESCOM electricity bill", "vendor": "BESCOM", "category": "electricity",
     "amount": 1380, "doc_date": _d(-65), "expiry_date": _d(-50)},
    {"kind": "bill", "title": "BESCOM electricity bill", "vendor": "BESCOM", "category": "electricity",
     "amount": 1510, "doc_date": _d(-35), "expiry_date": _d(-20)},
    {"kind": "bill", "title": "BESCOM electricity bill", "vendor": "BESCOM", "category": "electricity",
     "amount": 2390, "doc_date": _d(-5), "expiry_date": _d(10)},
    {"kind": "insurance", "title": "Car insurance policy", "vendor": "ICICI Lombard", "item_name": "Car insurance",
     "amount": 11200, "doc_date": _d(-355), "expiry_date": _d(10)},
    {"kind": "id_proof", "title": "Passport", "vendor": "Passport Seva", "item_name": "Passport",
     "doc_date": _d(-3500), "expiry_date": _d(150)},
]


def main():
    with session() as conn:
        if conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]:
            print("Database already has documents; not adding demo data.")
            return
        docs = [core.add_document(conn, d) for d in DEMO_DOCUMENTS]
        core.open_case(conn, "The fridge is not cooling properly and the compressor runs all the time.", docs[1]["id"])
        print(f"Added {len(docs)} demo documents and 1 complaint draft.")


if __name__ == "__main__":
    main()

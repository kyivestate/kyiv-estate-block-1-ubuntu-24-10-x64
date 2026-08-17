import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from parser_v2.services.commission import normalize_commission


def test_examples() -> None:
    cases = {
        ("", "Оренда без комісії для орендаря"): "Без комісії",
        ("Комісія 50", ""): "Комісія 50%",
        ("", "Послуги агенції: 2,5% від вартості"): "Комісія 2,5%",
        ("", "Комиссионные 1 500 грн"): "Комісія 1500 грн",
        ("", "Ціна 1 000 $, комісія обговорюється"): "Комісія: умови уточнюються",
        ("", "Жодної згадки про оплату послуг"): "Не вказано",
        ("Комісія 0%", ""): "Без комісії",
    }
    for (value, text), expected in cases.items():
        assert normalize_commission(value, text) == expected, (value, text)


if __name__ == "__main__":
    test_examples()
    print("commission extraction tests passed")

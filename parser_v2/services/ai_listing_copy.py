import re

BANNED = re.compile(r"комісі|ріелтор|риелтор|брокер|агент|власник|собственник|контакт|телефон|дзвон|звон|пишіть|звертайтеся|не турбувати|без посеред", re.I)
PHONE = re.compile(r"(?:\+?38)?[\s()\-]*0\d(?:[\s()\-]*\d){8,}")
URL = re.compile(r"https?://\S+|www\.\S+", re.I)
LEADING_LABEL = re.compile(r"^(?:опис|описание|description)\s*[:\-–—]*\s*", re.I)
COMPLEX_PREFIX = re.compile(r"^жк\s*", re.I)
REDACTIONS = (
    re.compile(r"\b(?:без\s+)?комісі\w*\b", re.I),
    re.compile(r"\b(?:від\s+)?(?:власник|собственник)\w*\b", re.I),
    re.compile(r"\b(?:ріелтор|риелтор|брокер|агент)\w*(?:\s+[А-ЯІЇЄҐA-Z][\w'’.-]+){0,3}", re.I),
    re.compile(r"\b(?:контакт|телефон|дзвон|дзвін|звон|пишіть|писати|звертайтеся|перепис|не\s+турбувати)\w*\b[^.!?\n]*", re.I),
    re.compile(r"\b(?:viber|telegram|whatsapp|whatsup)\b[^.!?\n]*", re.I),
)

def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()

def _number(value):
    if value is None or value == "":
        return ""
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number).replace(".", ",")
    except (TypeError, ValueError):
        return _text(value)

def _rooms_phrase(value):
    number = _number(value)
    try:
        integer = int(float(number.replace(",", ".")))
    except (AttributeError, ValueError):
        return f"{number} кімнат" if number else ""
    if integer == 1:
        return "1 кімнату"
    if integer % 10 in (2, 3, 4) and integer % 100 not in (12, 13, 14):
        return f"{integer} кімнати"
    return f"{integer} кімнат"

def _kind(row):
    value = _text(row.get("property_type")).lower()
    return "будинок" if value in {"будинок", "house"} else "квартира"

def _object_name(row, genitive=False):
    kind = _kind(row)
    rooms = _number(row.get("rooms"))
    if rooms:
        if genitive:
            return f"{rooms}-кімнатного {('будинку' if kind == 'будинок' else 'житла')}" if kind == "будинок" else f"{rooms}-кімнатної квартири"
        return f"{rooms}-кімнатний {kind}" if kind == "будинок" else f"{rooms}-кімнатна квартира"
    return "будинку" if genitive and kind == "будинок" else ("квартири" if genitive else kind)

def _complex_name(row):
    value = COMPLEX_PREFIX.sub("", _text(row.get("residential_complex"))).strip(" «»\"")
    value = re.split(BANNED, value, maxsplit=1)[0].strip(" ,.-–—")
    value = re.sub(r"\s+(?:від|з|у|на)$", "", value, flags=re.I)
    if len(value) > 100 or re.search(r"зда[єе]ть|оренд|продаж|квартир|будинок|метро|поверх", value, re.I):
        return ""
    return value

def _street(row):
    value = BANNED.sub("", _text(row.get("street"))).strip(" ,.-–—()!")
    if len(value) < 4 or len(value) > 100 or re.search(r"знаход|квартир|будинок|поверх|безкоштов|адреса|метро", value, re.I):
        return ""
    return value

def _metro(row):
    value = BANNED.sub("", _text(row.get("metro_station"))).strip(" ,.-–—()!")
    if len(value) > 80 or value.lower() in {"метро", "станція", "станция"} or re.search(r"знаход|квартир|будинок|поверх|вул", value, re.I):
        return ""
    return value

def build_title(row):
    action = "Оренда" if row.get("operation") == "rent" else "Продаж"
    parts = [action, _object_name(row, genitive=True)]
    area = _number(row.get("area"))
    if area:
        parts.append(f"{area} м²")
    district = _text(row.get("district"))
    complex_name = _complex_name(row)
    if complex_name:
        parts.append(f"у ЖК «{complex_name}»")
    elif district:
        parts.append(f"у {district} районі")
    else:


        parts.append("у Києві")
    return " ".join(parts)[:160]

def build_description(row):
    verb = "Пропонується в оренду" if row.get("operation") == "rent" else "Пропонується до продажу"
    first = f"{verb} {_object_name(row)}"
    area = _number(row.get("area"))
    if area:
        first += f" площею {area} м²"
    first += "."
    location = []
    district = _text(row.get("district"))
    complex_name = _complex_name(row)
    street = _street(row)
    metro = _metro(row)
    if district:
        location.append(f"{district} район")
    if complex_name:
        location.append(f"ЖК «{complex_name}»")
    if street:
        location.append(f"вул. {street}" if not street.lower().startswith(("вул", "вулиц", "просп", "бульв", "пров")) else street)
    if metro:
        location.append(f"метро {metro}")
    sentences = [first]
    if location:
        sentences.append("Розташування: " + ", ".join(location) + ".")
    floor = _number(row.get("floor"))
    floors = _number(row.get("floors_total"))
    if floor and floors:
        sentences.append(f"Поверх {floor} із {floors}.")
    elif floor:
        sentences.append(f"Поверх {floor}.")
    elif _kind(row) == "будинок" and floors:
        sentences.append(f"Будинок має {floors} поверхи.")
    return " ".join(sentences)[:800]

def clean_source_description(value):
    source = URL.sub("", PHONE.sub("", str(value or "")))
    english_marker = re.search(r"\*?\s*english\s+text", source, re.I)
    if english_marker and english_marker.start() > 500:
        source = source[:english_marker.start()]
    else:
        source = re.sub(r"\*?\s*english\s+text[^\n]*", "", source, flags=re.I)
    for pattern in REDACTIONS:
        source = pattern.sub(" ", source)
    paragraphs = re.split(r"\n\s*\n+", source)
    kept_paragraphs = []
    for paragraph in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        kept_sentences = []
        for sentence in sentences:
            sentence = LEADING_LABEL.sub("", _text(sentence))
            sentence = BANNED.sub("", sentence)
            if len(sentence) >= 12 and not BANNED.search(sentence):
                kept_sentences.append(sentence)
        if kept_sentences:
            kept_paragraphs.append(" ".join(kept_sentences))
    return "\n\n".join(kept_paragraphs)[:49000]

def factual_recap(row):
    facts = []
    rooms = _number(row.get("rooms"))
    area = _number(row.get("area"))
    district = _text(row.get("district"))
    street = _street(row)
    complex_name = _complex_name(row)
    metro = _metro(row)
    if rooms and area:
        facts.append(f"Планування передбачає {_rooms_phrase(rooms)}, а загальна площа становить {area} м².")
    elif area:
        facts.append(f"Загальна площа об'єкта становить {area} м².")
    if district or street or complex_name or metro:
        location = []
        if district: location.append(f"{district} район")
        if complex_name: location.append(f"ЖК «{complex_name}»")
        if street: location.append(street if street.lower().startswith(("вул", "вулиц", "просп", "бульв", "пров")) else f"вул. {street}")
        if metro: location.append(f"метро {metro}")
        facts.append("Локація, зазначена в оголошенні: " + ", ".join(location) + ".")
    floor = _number(row.get("floor"))
    floors = _number(row.get("floors_total"))
    if floor and floors:
        facts.append(f"Розташування на {floor} поверсі у {floors}-поверховому будинку.")
    return " ".join(facts)

def allowed_numbers(row, source):
    values = set(re.findall(r"\d+(?:[.,]\d+)?", source or ""))
    for key in ("rooms", "area", "floor", "floors_total"):
        value = _number(row.get(key))
        if value:
            values.add(value.replace(",", "."))
            values.add(value.replace(".", ","))
    return values

def valid_detailed_description(value, row, source):
    value = _text(value)
    if len(value) < 180 or len(value) > 49000 or BANNED.search(value) or PHONE.search(value) or URL.search(value):
        return False
    permitted = allowed_numbers(row, source)
    return all(number in permitted for number in re.findall(r"\d+(?:[.,]\d+)?", value))

def fallback_detailed_description(row, source):
    prefix = build_description(row)
    details = clean_source_description(source)
    if details:
        result = prefix + "\n\nДеталі об'єкта:\n" + details
    else:



        result = prefix + ("\n\nУ першоджерелі немає розгорнутого опису. "
                           "Наведено лише підтверджені характеристики об'єкта.")
    recap = factual_recap(row)
    if recap and len(result.split()) < 100:
        result += "\n\n" + recap
    return result[:49000]

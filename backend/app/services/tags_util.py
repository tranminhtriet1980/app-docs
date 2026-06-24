import json


def parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(t).strip() for t in data if str(t).strip()]
    except json.JSONDecodeError:
        pass
    return [t.strip() for t in raw.split(",") if t.strip()]


def dump_tags(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    cleaned = [t.strip() for t in tags if t and t.strip()]
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None

"""Static voice catalog and OpenAI voice resolver for Muse TTS."""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any

_VOICES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "voices.json")

DEFAULT_VOICE_ID = "avocado_v2:MAI_01"

OPENAI_VOICE_ALIASES: dict[str, str] = {
    "alloy": "avocado_v2:MAI_01",
    "echo": "avocado_v2:MAI_03",
    "fable": "avocado_v2:isabella",
    "onyx": "avocado_v2:magnus",
    "nova": "avocado_v2:paloma",
    "shimmer": "avocado_v2:lumi",
}

_PUBLIC_FIELDS = (
    "id",
    "name",
    "gender",
    "accent",
    "tone",
    "language",
    "tts_lang",
    "description",
    "long_description",
)

TTS_LANG_TO_NAME: dict[str, str] = {
    "en": "English",
    "vi": "Vietnamese",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "th": "Thai",
    "id": "Indonesian",
    "ar": "Arabic",
    "fi": "Finnish",
    "tl": "Filipino",
    "ms": "Malaysian",
    "hi": "Hindi",
}
LANGUAGE_GROUP_TO_CODE: dict[str, str] = {name: code for code, name in TTS_LANG_TO_NAME.items()}
_NAME_TO_CODE_LOWER: dict[str, str] = {name.lower(): code for code, name in TTS_LANG_TO_NAME.items()}

_VOICES_CACHE: list[dict[str, str]] | None = None
_BY_ID: dict[str, dict[str, str]] = {}
_BY_ID_LIST: dict[str, list[dict[str, str]]] = {}
_BY_NAME_LOWER: dict[str, dict[str, str]] = {}
_BY_NAME_LOWER_LIST: dict[str, list[dict[str, str]]] = {}


def _load_voices() -> list[dict[str, str]]:
    global _VOICES_CACHE
    if _VOICES_CACHE is not None:
        return _VOICES_CACHE

    with open(_VOICES_PATH, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    cleaned: list[dict[str, str]] = []
    for item in raw_list:
        vid = str(item.get("id") or "").strip()
        if not vid:
            continue
        entry = {k: str(item.get(k) or "") for k in _PUBLIC_FIELDS}
        tts_lang = str(item.get("tts_lang") or "").strip().lower()
        entry["tts_lang"] = tts_lang
        if tts_lang:
            entry["language"] = tts_lang
        cleaned.append(entry)
        if vid not in _BY_ID:
            _BY_ID[vid] = entry
        _BY_ID_LIST.setdefault(vid, []).append(entry)
        name_l = entry["name"].strip().lower()
        if name_l:
            if name_l not in _BY_NAME_LOWER:
                _BY_NAME_LOWER[name_l] = entry
            _BY_NAME_LOWER_LIST.setdefault(name_l, []).append(entry)

    _VOICES_CACHE = cleaned
    return _VOICES_CACHE


def get_voice_language_code(voice: dict[str, Any] | None) -> str:
    """Return the canonical ``tts_lang`` code (e.g. 'en', 'vi', 'ja') for a voice."""
    if not voice:
        return "en"
    return str(voice.get("tts_lang") or "").strip().lower() or "en"


def get_voice_language_group(voice: dict[str, Any]) -> str:
    """Return the display language name derived from ``tts_lang``."""
    code = str(voice.get("tts_lang") or "").strip().lower()
    if not code:
        return "Other"
    return TTS_LANG_TO_NAME.get(code, code.upper())


def _canonicalize_language_token(raw: str) -> str | None:
    """Map a language code, display name, or legacy English(*) name to canonical display name."""
    key = str(raw or "").strip().lower()
    if not key:
        return None
    if key == "eng" or key.startswith("english ("):
        return "English"
    if key in TTS_LANG_TO_NAME:
        return TTS_LANG_TO_NAME[key]
    if key in _NAME_TO_CODE_LOWER:
        return TTS_LANG_TO_NAME[_NAME_TO_CODE_LOWER[key]]

    # Dynamic fallback for any tts_lang present in voices.json outside TTS_LANG_TO_NAME
    for v in _load_voices():
        code = get_voice_language_code(v)
        group = get_voice_language_group(v)
        if key == code or key == group.lower():
            return group
    return None


def list_available_voice_languages() -> list[dict[str, Any]]:
    """Return languages present in ``voices.json`` with counts sorted by count desc then name asc."""
    voices = _load_voices()
    counts: Counter[tuple[str, str]] = Counter(
        (get_voice_language_group(v), get_voice_language_code(v)) for v in voices
    )
    items = [
        {"name": name, "code": code, "count": count}
        for (name, code), count in counts.items()
    ]
    items.sort(key=lambda x: (-x["count"], x["name"]))
    return items


def normalize_voice_languages(languages: list[str] | set[str] | None) -> list[str]:
    """Validate and normalize user-provided language names/codes to canonical unique display names."""
    if not languages:
        return []
    seen: set[str] = set()
    for raw in languages:
        canonical = _canonicalize_language_token(raw)
        if canonical:
            seen.add(canonical)
    ordered = [item["name"] for item in list_available_voice_languages() if item["name"] in seen]
    extra = sorted(name for name in seen if name not in ordered)
    return ordered + extra


def is_voice_allowed(voice: dict[str, Any], allowed_languages: list[str] | set[str] | None) -> bool:
    """Check if a voice's ``tts_lang`` / language group is in ``allowed_languages``."""
    if not allowed_languages:
        return True
    allowed_set: set[str] = set()
    for raw in allowed_languages:
        s = str(raw or "").strip()
        if not s:
            continue
        canonical = _canonicalize_language_token(s)
        allowed_set.add((canonical or s).lower())
    if not allowed_set:
        return True
    return (
        get_voice_language_group(voice).lower() in allowed_set
        or get_voice_language_code(voice).lower() in allowed_set
    )


def _match_voice_language(voice: dict[str, Any], language: str) -> bool:
    """Return True if a voice entry matches a requested ``tts_lang`` code or language name."""
    lang_l = str(language or "").strip().lower()
    if not lang_l:
        return True
    code = get_voice_language_code(voice).lower()
    group = get_voice_language_group(voice)
    if lang_l == code or lang_l == group.lower():
        return True
    canonical = _canonicalize_language_token(lang_l)
    if canonical and canonical.lower() == group.lower():
        return True
    return False


def list_voices(
    gender: str = "",
    accent: str = "",
    language: str = "",
    tone: str = "",
    q: str = "",
    allowed_languages: list[str] | set[str] | None = None,
) -> list[dict[str, str]]:
    """Return filtered public voices from the static catalog."""
    voices = _load_voices()
    g_f = gender.strip().lower()
    a_f = accent.strip().lower()
    l_f = language.strip().lower()
    t_f = tone.strip().lower()
    q_f = q.strip().lower()

    out: list[dict[str, str]] = []
    for v in voices:
        if allowed_languages and not is_voice_allowed(v, allowed_languages):
            continue
        if g_f and v["gender"].lower() != g_f:
            continue
        if a_f and v["accent"].lower() != a_f:
            continue
        if l_f and not _match_voice_language(v, l_f):
            continue
        if t_f and v["tone"].lower() != t_f:
            continue
        if q_f:
            haystack = " ".join(
                (
                    v["id"],
                    v["name"],
                    v["tts_lang"],
                    get_voice_language_group(v),
                    v["accent"],
                    v["tone"],
                    v["description"],
                    v["long_description"],
                )
            ).lower()
            if q_f not in haystack:
                continue
        out.append(v)
    return out


def has_multiple_language_groups(voice_id: str) -> bool:
    """Return True if a voice ID appears in the catalog under more than one language group."""
    _load_voices()
    entries = _BY_ID_LIST.get(voice_id.strip(), [])
    if len(entries) <= 1:
        return False
    groups = {get_voice_language_group(v) for v in entries}
    return len(groups) > 1


def resolve_voice(
    voice_input: str | None,
    language: str | None = None,
    allowed_languages: list[str] | set[str] | None = None,
) -> dict[str, str] | None:
    """Resolve voice by exact id, case-insensitive name, or OpenAI preset alias.

    When ``language`` is provided and multiple catalog entries share the same ID or name,
    prefer the entry matching ``language``. Otherwise, if ``allowed_languages`` is provided,
    prefer the first entry allowed by settings.
    """
    _load_voices()
    raw = (voice_input or "").strip()
    if not raw:
        if DEFAULT_VOICE_ID in _BY_ID:
            candidates = _BY_ID_LIST[DEFAULT_VOICE_ID]
            default_entry = _BY_ID[DEFAULT_VOICE_ID]
        elif _VOICES_CACHE:
            candidates = [_VOICES_CACHE[0]]
            default_entry = _VOICES_CACHE[0]
        else:
            return None
    else:
        candidates = None
        default_entry = None
        if raw in _BY_ID_LIST:
            candidates = _BY_ID_LIST[raw]
            default_entry = _BY_ID[raw]
        else:
            lowered = raw.lower()
            if lowered in _BY_NAME_LOWER_LIST:
                candidates = _BY_NAME_LOWER_LIST[lowered]
                default_entry = _BY_NAME_LOWER[lowered]
            else:
                alias_target = OPENAI_VOICE_ALIASES.get(lowered)
                if alias_target and alias_target in _BY_ID_LIST:
                    candidates = _BY_ID_LIST[alias_target]
                    default_entry = _BY_ID[alias_target]
                elif alias_target and _VOICES_CACHE:
                    candidates = [_VOICES_CACHE[0]]
                    default_entry = _VOICES_CACHE[0]

    if not candidates:
        return None

    lang_filter = (language or "").strip()
    if lang_filter:
        for entry in candidates:
            if _match_voice_language(entry, lang_filter):
                return entry
    elif allowed_languages:
        for entry in candidates:
            if is_voice_allowed(entry, allowed_languages):
                return entry

    return default_entry

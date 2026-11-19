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
    "description",
    "long_description",
)

_HIDDEN_VOICE_IDS = {"avocado_v2:p1a1_short"}

# Static 31 canonical language groups mapped from 36 accents + French Canadian (fra)
ACCENT_TO_LANGUAGE_GROUP: dict[str, str] = {
    # English by Country (13 groups, 999 voices)
    "american": "English (US)",
    "southern american": "English (US)",
    "new york": "English (US)",
    "mid-atlantic": "English (US)",
    "british": "English (UK)",
    "scottish": "English (UK)",
    "australian": "English (Australia)",
    "irish": "English (Ireland)",
    "south african": "English (South Africa)",
    "kenyan": "English (Kenya)",
    "nigerian": "English (Nigeria)",
    "trinidadian": "English (Trinidad)",
    "zimbabwean": "English (Zimbabwe)",
    "new zealand": "English (New Zealand)",
    "singaporean": "English (Singapore)",
    "jamaican": "English (Jamaica)",
    "canadian": "English (Canada)",
    # Other distinct languages (17 groups, 218 voices)
    "french": "French",
    "french canadian": "French",
    "indian": "Indian",
    "finnish": "Finnish",
    "indonesian": "Indonesian",
    "spanish": "Spanish",
    "german": "German",
    "brazilian": "Portuguese",
    "middle eastern": "Arabic",
    "filipino": "Filipino",
    "malaysian": "Malaysian",
    "chinese": "Chinese",
    "russian": "Russian",
    "italian": "Italian",
    "vietnamese": "Vietnamese",
    "thai": "Thai",
    "japanese": "Japanese",
    "korean": "Korean",
    # Other (1 voice)
    "transylvanian": "Other",
}

ENGLISH_LANGUAGE_GROUPS: tuple[str, ...] = (
    "English (US)",
    "English (UK)",
    "English (Australia)",
    "English (Ireland)",
    "English (South Africa)",
    "English (Kenya)",
    "English (Nigeria)",
    "English (Trinidad)",
    "English (Zimbabwe)",
    "English (New Zealand)",
    "English (Singapore)",
    "English (Jamaica)",
    "English (Canada)",
)

CANONICAL_LANGUAGE_GROUPS: tuple[str, ...] = (
    "English (US)",
    "English (UK)",
    "English (Australia)",
    "English (Ireland)",
    "French",
    "Indian",
    "English (South Africa)",
    "English (Kenya)",
    "English (Nigeria)",
    "English (Trinidad)",
    "Finnish",
    "English (Zimbabwe)",
    "Indonesian",
    "English (New Zealand)",
    "Spanish",
    "German",
    "English (Singapore)",
    "Arabic",
    "English (Jamaica)",
    "Portuguese",
    "Filipino",
    "Malaysian",
    "Chinese",
    "English (Canada)",
    "Russian",
    "Italian",
    "Thai",
    "Vietnamese",
    "Japanese",
    "Korean",
    "Other",
)

_CANONICAL_LOWER_MAP: dict[str, str] = {g.lower(): g for g in CANONICAL_LANGUAGE_GROUPS}

LANGUAGE_GROUP_TO_CODE: dict[str, str] = {
    "Vietnamese": "vi",
    "Japanese": "ja",
    "Korean": "ko",
    "Chinese": "zh",
    "French": "fr",
    "Spanish": "es",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Russian": "ru",
    "Thai": "th",
    "Indonesian": "id",
    "Arabic": "ar",
    "Finnish": "fi",
    "Filipino": "tl",
    "Malaysian": "ms",
}

_VOICES_CACHE: list[dict[str, str]] | None = None
_BY_ID: dict[str, dict[str, str]] = {}
_BY_NAME_LOWER: dict[str, dict[str, str]] = {}


def _load_voices() -> list[dict[str, str]]:
    global _VOICES_CACHE
    if _VOICES_CACHE is not None:
        return _VOICES_CACHE

    with open(_VOICES_PATH, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    cleaned: list[dict[str, str]] = []
    for item in raw_list:
        vid = str(item.get("id") or "").strip()
        if not vid or vid in _HIDDEN_VOICE_IDS:
            continue
        entry = {k: str(item.get(k) or "") for k in _PUBLIC_FIELDS}
        cleaned.append(entry)
        _BY_ID[vid] = entry
        name_l = entry["name"].strip().lower()
        if name_l and name_l not in _BY_NAME_LOWER:
            _BY_NAME_LOWER[name_l] = entry

    _VOICES_CACHE = cleaned
    return _VOICES_CACHE


def get_voice_language_group(voice: dict[str, Any]) -> str:
    """Determine the canonical language group of a voice."""
    if str(voice.get("language") or "").strip().lower() == "fra":
        return "French"
    accent = str(voice.get("accent") or "").strip().lower()
    return ACCENT_TO_LANGUAGE_GROUP.get(accent, "Other")


def get_voice_language_code(voice: dict[str, Any] | None) -> str:
    """Determine the short ISO language code (e.g. 'en', 'vi') for a voice."""
    if not voice:
        return "en"
    group = get_voice_language_group(voice)
    return LANGUAGE_GROUP_TO_CODE.get(group, "en")


def list_available_voice_languages() -> list[dict[str, Any]]:
    """Return available language groups with counts sorted by count desc then name asc."""
    voices = _load_voices()
    counts = Counter(get_voice_language_group(v) for v in voices)
    items: list[dict[str, Any]] = []
    for g in CANONICAL_LANGUAGE_GROUPS:
        items.append({"name": g, "count": counts.get(g, 0)})
    items.sort(key=lambda x: (-x["count"], x["name"]))
    return items


def normalize_voice_languages(languages: list[str] | set[str] | None) -> list[str]:
    """Validate and normalize user-provided language names to canonical unique list.
    Automatically expands legacy 'English' to all 13 English (*) country groups.
    """
    if not languages:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in languages:
        key = str(raw or "").strip().lower()
        if key == "english":
            for eng_group in ENGLISH_LANGUAGE_GROUPS:
                if eng_group not in seen:
                    seen.add(eng_group)
                    result.append(eng_group)
            continue
        canonical = _CANONICAL_LOWER_MAP.get(key)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    # Maintain canonical sort order
    return [g for g in CANONICAL_LANGUAGE_GROUPS if g in seen]


def is_voice_allowed(voice: dict[str, Any], allowed_languages: list[str] | set[str] | None) -> bool:
    """Check if a voice matches the allowed language groups."""
    if not allowed_languages:
        return True
    allowed_set = {str(l).strip().lower() for l in allowed_languages if str(l).strip()}
    if not allowed_set:
        return True
    return get_voice_language_group(voice).lower() in allowed_set


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

    allowed_set = {str(l).strip().lower() for l in allowed_languages or [] if str(l).strip()}

    out: list[dict[str, str]] = []
    for v in voices:
        # Enforce settings voice_languages filter when provided
        if allowed_set and get_voice_language_group(v).lower() not in allowed_set:
            continue

        if g_f and v["gender"].lower() != g_f:
            continue
        if a_f and v["accent"].lower() != a_f:
            continue

        # Match query param language against raw code ('fra'), canonical group ('English (US)', 'French'...),
        # or legacy "English" / "eng" which matches any group in ENGLISH_LANGUAGE_GROUPS
        if l_f:
            raw_lang = v["language"].lower()
            lang_group = get_voice_language_group(v)
            lang_group_l = lang_group.lower()
            if l_f in ("english", "eng"):
                if lang_group not in ENGLISH_LANGUAGE_GROUPS:
                    continue
            elif l_f != raw_lang and l_f != lang_group_l:
                continue

        if t_f and v["tone"].lower() != t_f:
            continue
        if q_f:
            haystack = " ".join(
                (v["id"], v["name"], v["accent"], v["tone"], v["description"], v["long_description"])
            ).lower()
            if q_f not in haystack:
                continue
        out.append(v)
    return out


def resolve_voice(voice_input: str | None) -> dict[str, str] | None:
    """Resolve voice by exact id, case-insensitive name, or OpenAI preset alias."""
    _load_voices()
    raw = (voice_input or "").strip()
    if not raw:
        if DEFAULT_VOICE_ID in _BY_ID:
            return _BY_ID[DEFAULT_VOICE_ID]
        return _VOICES_CACHE[0] if _VOICES_CACHE else None

    if raw in _BY_ID:
        return _BY_ID[raw]

    lowered = raw.lower()
    if lowered in _BY_NAME_LOWER:
        return _BY_NAME_LOWER[lowered]

    alias_target = OPENAI_VOICE_ALIASES.get(lowered)
    if alias_target and alias_target in _BY_ID:
        return _BY_ID[alias_target]
    if alias_target and _VOICES_CACHE:
        # Fallback to the first available voice if preset alias target is not in catalog
        return _VOICES_CACHE[0]

    return None

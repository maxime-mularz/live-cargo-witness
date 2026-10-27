"""Forbidden vocabulary (CLAUDE.md rule 5).

The agent reports deviations from rules; it never assesses the health or condition of animals.
Any agent statement containing one of these words is rejected by the verifier.
The list is deliberately broad; extend it, never shorten it to let a statement through.
"""

import re

FORBIDDEN_WORDS = (
    # English
    "veterinary", "vet", "diagnosis", "diagnose", "diagnosed", "sick", "sickness", "ill", "illness",
    "disease", "injured", "injury", "injuries", "wound", "wounded", "dead", "death", "died",
    "dying", "mortality", "suffering", "suffered", "distress", "dehydrated", "dehydration",
    "heat stress", "stressed", "symptom", "symptoms", "health", "healthy", "unhealthy", "lame",
    "lameness", "fever", "infection", "treatment", "euthanasia", "welfare",
    # French
    "vétérinaire", "veterinaire", "diagnostic", "malade", "maladie", "blessé", "blessée",
    "blessure", "mort", "morte", "décès", "deces", "mortalité", "souffrance", "stress thermique",
    "déshydratation", "symptôme", "symptome", "santé", "sante", "boiterie", "fièvre", "infection",
    "traitement", "bien-être", "bien-etre",
)

_PATTERNS = [
    re.compile(r"(?<![\w-])" + re.escape(word) + r"(?![\w-])", re.IGNORECASE)
    for word in FORBIDDEN_WORDS
]


def find_forbidden(text: str) -> list[str]:
    """Return the forbidden words found in ``text`` (case-insensitive, whole words)."""
    found = []
    for word, pattern in zip(FORBIDDEN_WORDS, _PATTERNS):
        if pattern.search(text or ""):
            found.append(word)
    return found

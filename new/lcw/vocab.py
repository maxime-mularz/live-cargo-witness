"""Forbidden vocabulary (CLAUDE.md rule 5).

The agent reports deviations from rules; it never assesses the health or condition of animals.
Any agent statement matching one of these patterns is rejected by the verifier.
Patterns are word stems so that plurals, verb forms and French agreement are caught
("death", "deaths"; "mort", "morts", "mortes"; "blessure", "blessures", "blessés").
Extend the list, never shorten it to let a statement through.
"""

import re

# (label, regex) — regexes are matched case-insensitively at a word start.
FORBIDDEN_STEMS = (
    # English
    ("veterinary", r"vet(erinar\w*|s)?"),
    ("diagnosis", r"diagnos\w*"),
    ("sick", r"sick\w*"),
    ("ill", r"ill(ness\w*)?"),
    ("disease", r"disease\w*"),
    ("injury", r"injur\w*"),
    ("wound", r"wound\w*"),
    ("dead", r"dead"),
    ("death", r"death\w*"),
    ("die", r"(die|died|dies|dying)"),
    ("mortality", r"mortalit\w*"),
    ("suffering", r"suffer\w*"),
    ("distress", r"distress\w*"),
    ("dehydration", r"dehydrat\w*"),
    ("stress", r"stress\w*"),
    ("symptom", r"symptom\w*"),
    ("health", r"(un)?health\w*"),
    ("lame", r"lame(ness)?"),
    ("fever", r"fever\w*"),
    ("infection", r"infect\w*"),
    ("treatment", r"treat(ment\w*|ed)"),
    ("euthanasia", r"euthan\w*"),
    ("welfare", r"welfare"),
    # French
    ("vétérinaire", r"v[ée]t[ée]rinaire\w*"),
    ("diagnostic", r"diagnosti\w*"),
    ("malade", r"malad\w*"),
    ("blessure", r"bless[ée]\w*|blessure\w*"),
    ("mort", r"mort(e|s|es|alit\w*)?"),
    ("décès", r"d[ée]c[èe]s|d[ée]c[ée]d\w*"),
    ("souffrance", r"souffr\w*"),
    ("stress", r"stress\w*"),
    ("déshydratation", r"d[ée]shydrat\w*"),
    ("symptôme", r"sympt[ôo]m\w*"),
    ("santé", r"sant[ée]"),
    ("boiterie", r"boit(erie\w*|eux|euse\w*)"),
    ("fièvre", r"fi[èe]vre\w*"),
    ("traitement", r"trait[ée]ment\w*"),
    ("bien-être", r"bien[- ][êe]tre"),
)

_PATTERNS = [(label, re.compile(r"(?<![\w-])(?:" + stem + r")(?![\w-])", re.IGNORECASE))
             for label, stem in FORBIDDEN_STEMS]


def find_forbidden(text: str) -> list[str]:
    """Return the labels of the forbidden words found in ``text``."""
    found = []
    for label, pattern in _PATTERNS:
        if pattern.search(text or "") and label not in found:
            found.append(label)
    return found


def mask_forbidden(text: str) -> str:
    """Replace forbidden words by ``[withheld]`` — for free model text (stated reasons, final
    messages) that the verifier does not check but the journal page displays."""
    for _, pattern in _PATTERNS:
        text = pattern.sub("[withheld]", text or "")
    return text

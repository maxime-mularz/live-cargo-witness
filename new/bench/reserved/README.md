# Reserved bench — sealed until the code freeze

Five fictitious dossiers written by an independent agent instance that was given only
[`../FORMAT.md`](../FORMAT.md) and the rule cards: it never saw the generator nor the development
bench, and the people tuning the agent never saw its dossiers.

Before the freeze, the repository holds only:
- `new/bench/reserved.tar.gz.enc` — the dossiers, encrypted (AES-256-CBC, PBKDF2);
- `new/bench/reserved.seal` — the SHA-256 seal of the plaintext dossiers.

After the code freeze (Nov 3, 2026, 6 PM Paris time), the dossiers are decrypted into this folder
with `new/scripts/unseal_bench.py`, the seal is checked, the agent runs on them **once**, and the
score is published as is, next to the development score.

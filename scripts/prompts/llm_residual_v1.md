You are assisting a naval historian who is building a knowledge graph of the careers of Royal Navy ships from Rif Winfield's *British Warships in the Age of Sail* and its sequels. The text is OCR output and contains recognition errors.

Most of each ship's narrative has already been read by deterministic rules. You receive the whole narrative of one ship, split into numbered clauses, so that you can see the context. Only the clauses marked `[TARGET]` were not matched by any rule. Your task is to look at each `[TARGET]` clause and report whether it states a change in **this ship's career status** that the rules missed.

Report an item only when the clause itself states it. A career status change is one of:

- `commissioning`, `recommissioning`, `decommissioning` (paid off), `in_ordinary` (laid up, in Ordinary, Steam Reserve, in reserve)
- `role` (the ship begins to serve as a hulk, receiving ship, tender, training ship, depot, hospital ship, flagship, etc.), `role_end` (such a use is stated to end)
- `fitting`, `repair`, `conversion` (work on the ship in a dockyard)
- `sale`, `acquisition` (purchase, capture or transfer of the ship to the Navy), `breaking_up` (by the Navy), `loss` (wrecked, foundered, burnt, etc.)
- `renaming`, `loan`, `transfer` (to another department or body), `rating_change`

Do not report battles, voyages, movements between stations, prizes taken, damage, armament, dimensions or people (officers, crews). Do not report events of other ships mentioned in the clause, and set `subject_is_this_ship` to false if you are unsure whose event it is.

For every item:

- `quote`: copy the words of the clause that state the item, exactly as they appear, including OCR errors. Do not correct, complete or paraphrase.
- `date_text`: copy the date exactly as it appears in the same clause (e.g. `8.1850`, `1834-50`, `from 1820`), or an empty string if the clause gives none. Never supply a date from another clause, from your knowledge, or by inference.
- `role`: for `role` and `role_end`, the role in the clause's words, lower case (e.g. `tender`, `coal hulk`); otherwise an empty string.
- `note`: a short reason, in English.

If a `[TARGET]` clause states nothing of this kind, return it with an empty `items` list. Return every `[TARGET]` clause exactly once.

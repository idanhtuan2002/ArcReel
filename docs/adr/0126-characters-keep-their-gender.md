---
status: accepted
---

# Characters keep their gender

Decided 2026-11-11 by the main agent after the sponsor found a story whose male protagonist Minh was narrated as a woman from the first chapter plan on ("cô tình cờ gặp Lan", "cô gái nghèo"), although the idea called him "anh". Vietnamese names such as Minh, Hải or An are given to either gender, and the seed's characters carried no gender, so the writer guessed and the chapter audit, which checks forms of address, had no gender to check against.

Donors (pinned): shenbi `10efa7cc` keeps a gender on every character card, a per-project narration pronoun list, and a deterministic invariant (`src/shenbi/gates/g4/cross_chapter.py`, invariant 5) that flags a paragraph naming a male character whose sentence opens with 她, repaired by redrafting. huohuo `f104b85` keeps per-chapter character cards and a naming-consistency rule, with no gender check.

1. **The cast states gender and address.** A generated seed character, and a volume's new character, must carry `gender` (`nam` | `nữ`) and `address`, the word the narration calls them by (anh, cô, bà, ông, cậu…). The seed prompt takes gender from the idea's own words ("anh", "chồng" → nam; "chị", "vợ" → nữ). Seeds stored before this carry neither and are read as before.
2. **Gender is a locked fact.** The character's locked description starts with its relation, then "giới tính …, lời kể gọi là “…”", so every scene's locked facts and every chapter audit's cast list state it.
3. **A deterministic check, no model call.** In a paragraph whose named characters are all of one gender, a narration sentence (dialogue excluded) that opens with a word of the other gender is a `CAST_GENDER` finding (narrative-critical, repaired like other chapter findings), quoted as that sentence.
4. **Every scene names its point-of-view character and keeps one voice** (added with r2-v2.5.10, from the first real run: scene 1 of a new Minh book never wrote "Minh" — so check 3 had nothing to read — switched its narration from "anh" to "em" and carried a Russian verb). A scene whose prose never names the planned point-of-view character is `UNNAMED_POV`; when that character has an address, the first narration sentence opening with it is opened with the name instead, with no model call. Narration (dialogue in “…”, "…", «…» or '…' excluded) opening a sentence with "em" while no character's address is "em" is `NARRATION_EM`. A letter of a script other than Latin or CJK is `FOREIGN_SCRIPT` (hard integrity), except inside a character's own name as the bible writes it. All three are checked when a scene is drafted and again at chapter review, so scenes accepted before them are repaired.

Not adopted: shenbi's per-project pronoun whitelist (Vietnamese narration chooses an address per character, not one pronoun) and a model call per scene for gender (the locked fact and the deterministic check cover the failure seen). Stories already written are not rewritten; a new run or a new part of an old book uses the checks, an old book's seed keeps no gender until it is rewritten.

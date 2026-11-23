# Story quality: huohuo in Chinese then translated, or written directly in Vietnamese?

Date: 2026-11-23. Sponsor question. Labels: **FACT** (source), **INFER**.

## 1. Facts

Internal:
- huohuo's engine is the only full long-form engine among the donors (2026-11-08 study §2); its prompts, genre skills
  and deterministic checks are written for Chinese (no language handling in `workbench-server/src/services/novel/`;
  length limits in Chinese characters, `common/novel/novel-char-limit.ts`).
- Our free-model probe of a Vietnamese scene ranked `baidu/ernie-5.5-flash-preview:free` best ("natural prose, sharp
  dialogue"); several free models leak Han characters or other scripts into Vietnamese (`docs/r2/cloud-free-quota-registry.md`).
- Our own Vietnamese engine (re-implementation of huohuo/shenbi mechanisms) ended five story runs FAILED_QUALITY on
  11-14/15 (resource waste audit).
- Our translation (`lib/story_translation.py`) checks paragraph count, protected names, length band and no CJK, retries
  three times; it does not check style or idiom.

External:
- Web-novel translation is hard on idioms, lexical ambiguity and zero pronouns; Chinese-trained models translate Chinese
  web novels better than larger Western models (DITING benchmark, [arXiv 2510.09116](https://arxiv.org/html/2510.09116v2)).
- Standard and LLM metrics misalign with expert judgement of literary translation (LiTransProQA,
  [arXiv 2505.05423](https://arxiv.org/pdf/2505.05423v4)).
- A Vietnamese study of Gemini 2.0 Flash translating a literary work: literal accuracy, but humour and stylistic
  creativity are lost ([VJOL](https://www.vjol.info.vn/NCNN/en/article/view/124554)).
- LLM text in non-English languages shows elevated "translationese" even when generated natively
  ([arXiv 2608.17399](https://arxiv.org/pdf/2608.17399)); GPT-4's creative writing degrades outside English
  ([arXiv 2407.01119](https://arxiv.org/pdf/2407.01119)).
- For low-resource languages, native generation scored higher cultural relevance than machine translation with
  post-editing ([arXiv 2502.12932](https://arxiv.org/pdf/2502.12932)).

## 2. Comparison (INFER from §1)

| | huohuo (zh) → translation | Written directly in Vietnamese |
|---|---|---|
| Story engine (plan, memory, change records, audits, genre skills) | full, the donor's own | no donor engine writes Vietnamese whole: huohuo would need a language seam (prompts' output language, Chinese-character checks) — a donor change not covered by GOAL's amendment; our old engine is a re-implementation that failed |
| Prose quality in the source | Chinese-native model writing Chinese: its strongest case | free models in Vietnamese: ERNIE good in a scene probe; others leak scripts |
| Losses | translation loses humour, wordplay, voice; Chinese idioms; names become Hán-Việt | translationese still present; weaker creativity than in the model's strongest language |
| Culture and setting | Chinese setting and web-novel idiom by default; `setting = vn` asks for Vietnam but idiom stays Chinese | Vietnamese setting and idiom natural |
| Fit by genre | strong for genres read in Vietnam as translated Chinese web novels (tiên hiệp, ngôn tình cổ đại, xuyên không, hệ thống, báo thù) | strong for Vietnamese-life genres (gia đình, học đường, đời thường, kinh dị dân gian, truyện có thật) |

## 3. Result

- **Setting `original`** (Chinese genres): huohuo → translation. The main loss is translation style; measured on the first
  story (sponsor reads the Vietnamese text).
- **Setting `vn`** (Vietnamese life): huohuo → translation carries a Chinese idiom; direct Vietnamese needs an engine no
  donor provides whole. Evidence is not enough to choose: **the first `vn` story is written both ways from the same premise
  (text only, cheap) and the sponsor chooses** — (a) huohuo + translation, (b) huohuo with a Vietnamese-output seam
  (needs a GOAL decision), (c) the old app's Vietnamese engine.
- Recorded in the checklist as M3 items.

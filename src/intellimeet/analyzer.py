"""Turn a transcript into meeting intelligence and answer questions about it.

Providers:
  openai  - GPT models through the OpenAI API
  gemini  - Google Gemini through the google-genai SDK
  basic   - offline, rule-based fallback (no API key needed; lower quality)
  auto    - first configured of openai -> gemini -> basic
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import Counter
from typing import Any

from .config import Settings

log = logging.getLogger(__name__)

MAX_CHARS = 120_000
# Tried in order when the configured Gemini model is overloaded (503/429) or unavailable (404).
# Free tier (Nov 2026): Flash-Lite models allow ~500 requests/day, 3.8/3.6 Flash only ~20/day.
GEMINI_FALLBACKS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"]

ANALYSIS_PROMPT = """You are an expert meeting analyst. Analyse the meeting transcript below and
return ONLY a JSON object with exactly these keys:

{
  "title": "short descriptive meeting title (max 8 words)",
  "summary": "an abstract summary of the meeting in 3-5 sentences",
  "key_points": ["the most important points discussed, 3-8 items"],
  "decisions": ["decisions that were made; empty list if none"],
  "action_items": [{"task": "what must be done", "owner": "person or null", "due": "deadline or null"}],
  "topics": ["2-6 short topic tags"],
  "sentiment": {"label": "positive | neutral | negative | mixed",
                "score": number between -1 and 1,
                "explanation": "one sentence on the overall tone"}
}

Use only information present in the transcript. Do not invent names or dates.

Transcript:
\"\"\"
{transcript}
\"\"\""""

CHAT_SYSTEM = """You are IntelliMeet, an assistant that answers questions about one meeting.
Answer using only the transcript and analysis provided. If the answer is not in the meeting,
say so plainly. Be concise; use short bullet lists where helpful. When you quote, quote briefly."""


class AnalysisError(RuntimeError):
    pass


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def normalize_analysis(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce model output into a stable schema the UI can rely on."""
    sentiment = data.get("sentiment") or {}
    if isinstance(sentiment, str):
        sentiment = {"label": sentiment}
    try:
        score = float(sentiment.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    items = []
    for it in data.get("action_items") or []:
        if isinstance(it, str):
            it = {"task": it}
        task = (it.get("task") or "").strip()
        if task:
            items.append(
                {
                    "task": task,
                    "owner": it.get("owner") or None,
                    "due": it.get("due") or None,
                    "done": bool(it.get("done", False)),
                }
            )
    as_list = lambda v: [str(x).strip() for x in (v or []) if str(x).strip()]  # noqa: E731
    return {
        "title": (data.get("title") or "Untitled meeting").strip(),
        "summary": (data.get("summary") or "").strip(),
        "key_points": as_list(data.get("key_points")),
        "decisions": as_list(data.get("decisions")),
        "action_items": items,
        "topics": as_list(data.get("topics"))[:6],
        "sentiment": {
            "label": str(sentiment.get("label") or "neutral").lower(),
            "score": max(-1.0, min(1.0, score)),
            "explanation": sentiment.get("explanation") or "",
        },
    }


class MeetingAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._last_model = ""

    @property
    def provider(self) -> str:
        p = self.settings.analyzer
        if p != "auto":
            return p
        if self.settings.openai_api_key:
            return "openai"
        if self.settings.gemini_api_key:
            return "gemini"
        return "basic"

    # ----------------------------------------------------------------- analysis
    def analyze(self, transcript: str) -> dict[str, Any]:
        transcript = transcript.strip()
        if not transcript:
            raise AnalysisError("The transcript is empty - no speech was detected in the recording.")
        provider = self.provider
        if provider == "basic":
            result = BasicAnalyzer().analyze(transcript)
            result["provider"] = "basic"
            return result
        prompt = ANALYSIS_PROMPT.replace("{transcript}", transcript[:MAX_CHARS])
        try:
            raw = self._complete(provider, prompt, json_mode=True)
            result = normalize_analysis(_extract_json(raw))
            result["provider"] = f"{provider} · {self._last_model}"
        except Exception as exc:  # noqa: BLE001
            # Don't lose the meeting because the AI service is busy - use the offline analyzer
            # and say so. "Re-process recording" can be used later for a full AI summary.
            log.warning("AI analysis failed (%s); using offline analyzer", exc)
            result = BasicAnalyzer().analyze(transcript)
            result["provider"] = f"offline (the {provider} service was unavailable)"
            result["warning"] = f"The AI service was unavailable, so this summary was made offline: {str(exc)[:200]}"
        return result

    # --------------------------------------------------------------------- chat
    def answer(self, question: str, transcript: str, analysis: dict | None, history: list[dict] | None = None) -> str:
        provider = self.provider
        if provider == "basic":
            return BasicAnalyzer().answer(question, transcript, analysis)
        try:
            return self._answer_ai(provider, question, transcript, analysis, history)
        except Exception as exc:  # noqa: BLE001
            log.warning("AI chat failed (%s); answering offline", exc)
            return BasicAnalyzer().answer(question, transcript, analysis).replace(
                "_Offline mode: add an OpenAI or Gemini API key for full AI answers._",
                f"_The AI service didn't answer ({str(exc)[:160]}), so this is an offline answer._")

    def _answer_ai(self, provider, question, transcript, analysis, history) -> str:
        context = (
            f"Meeting analysis (JSON):\n{json.dumps(analysis or {}, indent=1)}\n\n"
            f"Transcript:\n{transcript[:MAX_CHARS]}"
        )
        turns = [{"role": "system", "content": CHAT_SYSTEM + "\n\n" + context}]
        for h in (history or [])[-8:]:
            if h.get("role") in {"user", "assistant"} and h.get("content"):
                turns.append({"role": h["role"], "content": h["content"]})
        turns.append({"role": "user", "content": question})
        return self._chat(provider, turns)

    # ---------------------------------------------------------------- providers
    def _complete(self, provider: str, prompt: str, json_mode: bool = False) -> str:
        return self._chat(provider, [{"role": "user", "content": prompt}], json_mode=json_mode)

    def _chat(self, provider: str, messages: list[dict], json_mode: bool = False) -> str:
        s = self.settings
        if provider == "openai":
            if not s.openai_api_key:
                raise AnalysisError("OPENAI_API_KEY is not set")
            from openai import OpenAI

            client = OpenAI(api_key=s.openai_api_key, timeout=90, max_retries=1)
            kwargs: dict[str, Any] = {"model": s.gpt_model, "messages": messages, "temperature": 0.2}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**kwargs)
            self._last_model = s.gpt_model
            return resp.choices[0].message.content or ""
        if provider == "gemini":
            if not s.gemini_api_key:
                raise AnalysisError("GEMINI_API_KEY is not set")
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise AnalysisError("Install the Gemini SDK: pip install google-genai") from exc
            # 90 s timeout so a blocked network shows an error instead of hanging forever
            client = genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(timeout=90_000))
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
            contents = [
                types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
                for m in messages
                if m["role"] != "system"
            ]
            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.2,
                response_mime_type="application/json" if json_mode else None,
            )
            models = [s.gemini_model] + [m for m in GEMINI_FALLBACKS if m != s.gemini_model]
            last_exc: Exception | None = None
            for model in models:
                for attempt in range(2):
                    try:
                        resp = client.models.generate_content(model=model, contents=contents, config=config)
                        self._last_model = model
                        return resp.text or ""
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        text = str(exc)
                        quota = "429" in text or "RESOURCE_EXHAUSTED" in text
                        busy = any(k in text for k in ("503", "UNAVAILABLE", "overloaded", "high demand"))
                        missing = "404" in text or "NOT_FOUND" in text
                        if not (quota or busy or missing):
                            raise
                        log.warning("Gemini %s: %s", model, text[:120])
                        if quota or missing or attempt == 1:
                            break  # quota/404: this model won't work now - go to the next one
                        time.sleep(4)
            reason = str(last_exc)
            if "429" in reason or "RESOURCE_EXHAUSTED" in reason:
                raise AnalysisError("Gemini's free daily limit is used up for all models - it resets in a few hours "
                                    f"(or add billing in AI Studio). ({reason[:120]})")
            raise AnalysisError(f"Gemini is busy right now - try again in a few minutes. ({reason[:150]})")
        raise AnalysisError(f"Unknown analyzer provider: {provider}")


# ---------------------------------------------------------------------------
# Offline fallback
# ---------------------------------------------------------------------------

STOPWORDS = set(
    """a about above after again against all am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have
    having he her here hers herself him himself his how i if in into is it its itself just me more most my
    myself no nor not now of off on once only or other our ours ourselves out over own same she should so
    some such than that the their theirs them themselves then there these they this those through to too
    under until up very was we were what when where which while who whom why will with would you your
    yours yourself yourselves also okay ok yeah yes um uh like gonna going get got let lets thing things
    think know really right well actually maybe one two us oh hey hi sure go see say said kind sort welcome everyone team meeting today
    need needs send still next first week anything something everything want wanted bit lot much many
    good great thanks thank last make made back time says said okay guys quickly week discuss
    yeah hmm everybody anyone someone thing still sure should would could also first one more work working
    january february march april june july august september october november december monday tuesday
    wednesday thursday friday saturday sunday tomorrow today evening morning""".split()
)
POSITIVE = set(
    "good great excellent awesome happy glad agree success successful progress improved improve love nice "
    "perfect thanks thank appreciate excited ahead win wins solved resolved easy clear helpful strong done "
    "completed finished working".split()
)
NEGATIVE = set(
    "bad issue issues problem problems blocker blocked blocking delay delayed risk risks concern concerns worried "
    "fail failed failing failure bug bugs broken difficult hard confused unclear late behind disagree slow stuck".split()
)
DAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
DATE = r"\d{1,2}(?:st|nd|rd|th)?(?:\s+of)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
DUE_RE = re.compile(
    rf"\b(?:by|before|on|until|till|due)\s+((?:next\s+|this\s+)?{DAY}(?:,?\s*{DATE})?(?:\s+(?:morning|evening|night|eod))?"
    rf"|{DATE}|tomorrow(?:\s+(?:morning|evening|night))?(?:,?\s*{DATE})?|today|tonight|eod|end of (?:the )?(?:day|week|month|sprint)"
    rf"|next week|this week)",
    re.IGNORECASE,
)
# A real commitment: someone says they / someone will do something.
COMMIT_RE = re.compile(
    r"\b(i'll|i will|we'll|we will|you'll|he'll|she'll|they'll|will (?:prepare|share|send|finish|complete|work|fix|test|"
    r"update|create|build|write|review|handle|take|deliver|integrate|deploy)|i need to|we need to|still need to|needs to|have to|"
    r"has to|going to|i'm going to|action item|to-?do|follow up on|responsible for|take (?:care|responsibility) (?:of|for))\b",
    re.IGNORECASE,
)
FILLER_RE = re.compile(r"^(?:(?:okay|ok|so|yeah|yes|alright|right|um+|uh+|well|and|also|guys|then)[,.!]?\s+)+", re.IGNORECASE)
SAYS_RE = re.compile(r"\b([A-Z][a-z]{2,})\s+(?:says|said|will|can|should|is going to|needs to)\b")
VOCATIVE_RE = re.compile(r"^([A-Z][a-z]{2,}),")
DECISION_RE = re.compile(
    r"\b(decided|agreed|we'll go with|let's go with|final(?:ly|ised|ized)?|approved|we need to make sure|"
    r"the plan is|we will use|we'll use|settled on)\b",
    re.IGNORECASE,
)
NOT_NAMES = {"Okay", "Yeah", "Yes", "So", "And", "But", "Also", "Then", "Let", "Let's", "One", "The", "This", "That",
             "We", "I", "You", "Our", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
             "November", "December", "January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "Thanks", "Great", "Sure", "Right", "Alright", "What", "Are", "Can", "Who"}


def _clean(sentence: str) -> str:
    s = FILLER_RE.sub("", sentence.strip()).strip()
    return (s[:1].upper() + s[1:]) if s else s


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.split()) >= 4]


def _words(text: str) -> list[str]:
    toks = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    return [w for w in toks if "'" not in w and w not in STOPWORDS and len(w) > 2]


class BasicAnalyzer:
    """Rule-based extractive analysis, used when no AI service is available."""

    def analyze(self, transcript: str) -> dict[str, Any]:
        raw_sents = _sentences(transcript) or [transcript]
        sents = [_clean(x) for x in raw_sents]
        caps = Counter(re.findall(r"\b([A-Z][a-z]{2,})\b", transcript))
        names = {w for w, n in caps.items()
                 if w not in NOT_NAMES and n == len(re.findall(rf"\b{w}\b", transcript, re.I))}
        lower_names = {n.lower() for n in names}
        freq = Counter(w for w in _words(transcript) if w not in lower_names)
        top = freq.most_common(1)[0][1] if freq else 1

        def informative(x: str) -> bool:
            return not x.endswith("?") and len(_words(x)) >= 3

        def score(x: str) -> float:
            ws = _words(x)
            return sum(freq[w] / top for w in ws) / math.sqrt(len(ws) + 1) if ws else 0

        # ---- action items: commitments, with owner + deadline when we can find them
        actions, seen = [], set()
        for raw, x in zip(raw_sents, sents):
            if x.endswith("?") or not COMMIT_RE.search(x):
                continue
            if re.match(r"(?i)^let'?s (?:discuss|start|go over|begin|talk|quickly)", x):
                continue
            due = DUE_RE.search(x)
            owner = None
            m = SAYS_RE.search(raw) or VOCATIVE_RE.match(raw)
            if m and m.group(1) in names:
                owner = m.group(1)
            task = re.sub(r"(?i)^[A-Z][a-z]+ says that\s+", "", x).rstrip(".")
            key = task.lower()[:60]
            if key in seen:
                continue
            seen.add(key)
            actions.append({"task": task, "owner": owner, "due": due.group(1).strip(" ,") if due else None})

        decisions = [x for x in sents if DECISION_RE.search(x) and not x.endswith("?")][:5]

        pool = [i for i, x in enumerate(sents) if informative(x)] or list(range(len(sents)))
        ranked = sorted(pool, key=lambda i: score(sents[i]), reverse=True)
        summary_idx = sorted(ranked[:4])
        key_points = [sents[i] for i in sorted(ranked[:7])]

        words = re.findall(r"[a-z]+", transcript.lower())
        pos = sum(w in POSITIVE for w in words)
        neg = sum(w in NEGATIVE for w in words)
        score_val = (pos - neg) / (pos + neg + 4)
        label = "positive" if score_val > 0.2 else "negative" if score_val < -0.2 else "neutral"
        if pos >= 3 and neg >= 3 and abs(score_val) < 0.35:
            label = "mixed"

        # topics: frequent content words plus common two-word phrases ("api structure", "speaker identification")
        bigrams = Counter()
        toks = [w for w in re.findall(r"[a-z]+", transcript.lower())]
        for a, b in zip(toks, toks[1:]):
            if a not in STOPWORDS and b not in STOPWORDS and len(a) > 2 and len(b) > 2 and a not in lower_names and b not in lower_names:
                bigrams[f"{a} {b}"] += 1
        topics = [b.title() for b, n in bigrams.most_common(4) if n >= 2]
        for w, _ in freq.most_common(10):
            if len(topics) >= 6:
                break
            if not any(w in t.lower() for t in topics):
                topics.append(w.title())
        title = (" & ".join(topics[:2]) + " meeting") if topics else "Meeting"

        people = sorted({a["owner"] for a in actions if a["owner"]} | (names & set(SAYS_RE.findall(transcript))))
        summary = " ".join(sents[i] for i in summary_idx)
        if actions:
            summary += f" {len(actions)} action item{'s were' if len(actions) != 1 else ' was'} identified"
            summary += f", involving {', '.join(people)}." if people else "."
        return normalize_analysis(
            {
                "title": title,
                "summary": summary,
                "key_points": key_points,
                "decisions": decisions,
                "action_items": actions[:12],
                "topics": topics,
                "sentiment": {
                    "label": label,
                    "score": round(score_val, 2),
                    "explanation": f"Estimated offline from {pos} positive and {neg} negative cue words.",
                },
            }
        )

    def answer(self, question: str, transcript: str, analysis: dict | None = None) -> str:
        note = "\n\n_Offline mode: add an OpenAI or Gemini API key for full AI answers._"
        ql = question.lower()
        a = analysis or {}
        if a.get("action_items") and re.search(r"\b(who|responsib|owner|action|task|todo|to-do|follow)", ql):
            lines = []
            for it in a["action_items"]:
                meta = ", ".join(x for x in (it.get("owner"), f"due {it['due']}" if it.get("due") else None) if x)
                lines.append(f"- {it['task']}" + (f" (**{meta}**)" if meta else ""))
            return "Action items from this meeting:\n\n" + "\n".join(lines) + note
        if a.get("decisions") and re.search(r"\bdecid|decision|agree", ql):
            return "Decisions made:\n\n" + "\n".join(f"- {d}" for d in a["decisions"]) + note
        if a.get("summary") and re.search(r"\b(summar|overview|tl;?dr|about|recap|email)", ql):
            return a["summary"] + note
        q = set(_words(question))
        sents = _sentences(transcript)
        scored = sorted(((len(q & set(_words(s))), s) for s in sents), reverse=True)
        hits = [s for n, s in scored[:3] if n > 0]
        if not hits:
            return "I couldn't find anything in this meeting's transcript that matches that question." + note
        return "Here's what the transcript says that looks most relevant:\n\n" + "\n".join(f"- {h}" for h in hits) + note

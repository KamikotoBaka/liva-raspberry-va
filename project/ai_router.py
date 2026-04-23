from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request


@dataclass
class RouteDecision:
    route: str
    reason: str
    intent_guess: str


class AIRouter:
    """
    Two-tier intent recognition system optimized for Raspberry Pi:
    1. Fast Tier: Pattern-based intent matching (regex, instant response)
    2. Smart Tier: LLM-based classification (fallback for unknowns)
    
    Uses lightweight non-thinking model (qwen2.5:1.5b-instruct) only.
    """
    
    def __init__(self, dispatcher, settings_getter) -> None:
        self.dispatcher = dispatcher
        self.settings_getter = settings_getter
        self.ollama_url = os.getenv("LIVA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self.model = os.getenv("LIVA_MODEL", "qwen2.5:1.5b-instruct")

    def handle_text(self, text: str) -> dict:
        normalized_text = text.strip()
        if not normalized_text:
            return {
                "sttText": "",
                "commandText": "",
                "ttsText": "Please tell me what you need.",
                "intent": "empty_input",
                "route": "pattern",
                "routeReason": "No input provided",
                "intentGuess": "empty_input",
            }

        # TIER 1: Try fast pattern matching first
        intent, entity = self.dispatcher.resolve_intent(normalized_text)
        
        if intent != "unknown":
            # Fast path: matched a known pattern
            dispatch_result = self.dispatcher.dispatch(normalized_text)
            return {
                "sttText": normalized_text,
                "commandText": dispatch_result.get("command", ""),
                "ttsText": dispatch_result.get("tts_text", ""),
                "intent": intent,
                "route": "pattern",
                "routeReason": "Matched pattern-based intent",
                "intentGuess": intent,
                "errorEventId": (dispatch_result.get("error_event") or {}).get("id"),
                "errorTimestamp": (dispatch_result.get("error_event") or {}).get("timestamp"),
            }

        # TIER 2: Unknown intent - try LLM classification
        return self._handle_unknown_intent(normalized_text)

    def _handle_unknown_intent(self, text: str) -> dict:
        """Fallback to LLM for unknown intents or questions."""
        # Detect if it looks like a question
        is_question = self._looks_like_question(text)
        
        if is_question:
            # Answer question using LLM
            answer = self._answer_question(text)
            return {
                "sttText": text,
                "commandText": "LLM_ANSWER",
                "ttsText": answer,
                "intent": "question",
                "route": "llm",
                "routeReason": "Detected question pattern",
                "intentGuess": "question",
                "errorEventId": None,
                "errorTimestamp": None,
            }
        
        # Try LLM to classify the command intent
        classified_intent = self._classify_with_llm(text)
        
        if classified_intent and classified_intent != "unknown":
            # LLM classified it as a command type, try to execute it
            return {
                "sttText": text,
                "commandText": f"LLM_CLASSIFIED: {classified_intent}",
                "ttsText": f"I think you want to {classified_intent}, but I don't have a handler for that yet.",
                "intent": classified_intent,
                "route": "llm",
                "routeReason": f"LLM classified as: {classified_intent}",
                "intentGuess": classified_intent,
                "errorEventId": None,
                "errorTimestamp": None,
            }
        
        # Still unknown - ask for clarification
        return {
            "sttText": text,
            "commandText": "NO_MATCH",
            "ttsText": "I didn't understand that. Could you rephrase it?",
            "intent": "unknown",
            "route": "none",
            "routeReason": "No pattern match and LLM could not classify",
            "intentGuess": "unknown",
            "errorEventId": None,
            "errorTimestamp": None,
        }

    def _looks_like_question(self, text: str) -> bool:
        """Quick check for question patterns without LLM."""
        lowered = text.strip().lower()
        
        # Ends with question mark
        if lowered.endswith("?"):
            return True
        
        # Starts with question words
        question_starters = (
            "what ", "why ", "how ", "when ", "where ", "who ", 
            "which ", "can you ", "could you ", "tell me "
        )
        return lowered.startswith(question_starters)

    def _classify_with_llm(self, text: str) -> str | None:
        """Use LLM to classify unknown intent."""
        prompt = (
            "Classify this voice command into ONE intent type. "
            "Return ONLY the intent name (no quotes, no explanation).\n"
            "Common intents: turn_on_device, turn_off_device, play_music, "
            "set_timer, adjust_temperature, open_app, get_weather, unknown\n\n"
            f"Command: {text}\n"
            "Intent:"
        )
        
        response = self._call_ollama(prompt)
        if not response:
            return None
        
        # Extract first word (intent name)
        intent = response.strip().split()[0].lower() if response.strip() else None
        
        # Validate it's a reasonable intent
        if intent and len(intent) < 50 and "_" in intent or intent.isalpha():
            return intent
        
        return None

    def _answer_question(self, text: str) -> str:
        """Use LLM to answer a question."""
        prompt = (
            "You are LIVA, a concise voice assistant. "
            "Answer the question clearly and briefly (under 50 words). "
            "Avoid unsafe actions.\n\n"
            f"Question: {text}\n"
            "Answer:"
        )
        
        answer = self._call_ollama(prompt)
        if not answer:
            return "I couldn't process your question right now. Please try again."
        
        return answer.strip()

    def _call_ollama(self, prompt: str) -> str | None:
        """Call Ollama API with the lightweight model."""
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "num_predict": 100,  # Limit output for faster response
        }).encode("utf-8")
        
        req = urllib_request.Request(
            url=f"{self.ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        try:
            with urllib_request.urlopen(req, timeout=15) as response:
                body = response.read().decode("utf-8", errors="ignore")
                data = json.loads(body)
                return data.get("response", "").strip()
        except (urllib_error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
#!/usr/bin/env python3
"""
Test script to demonstrate the two-tier intent recognition system.

Usage:
    python test_intent_routing.py "turn on the lights"
    python test_intent_routing.py "what is machine learning?"
    python test_intent_routing.py "play my favorite song"
"""

import json
from ai_router import AIRouter
from dispatcher import CommandDispatcher
from error_store import ErrorStore


def mock_settings_getter():
    """Mock settings for testing."""
    return {
        "responseMode": "command",
        "computeDevice": "cpu"
    }


def test_intent_routing():
    """Test the two-tier intent routing system."""
    
    # Initialize components
    error_store = ErrorStore()
    dispatcher = CommandDispatcher(error_store=error_store)
    router = AIRouter(dispatcher=dispatcher, settings_getter=mock_settings_getter)
    
    # Test cases demonstrating both tiers
    test_cases = [
        {
            "input": "turn on the kitchen lights",
            "expected_tier": "TIER 1 (Pattern)",
            "description": "Simple light command"
        },
        {
            "input": "what is machine learning?",
            "expected_tier": "TIER 2 (LLM - Question)",
            "description": "Question requiring LLM"
        },
        {
            "input": "show last 3 errors",
            "expected_tier": "TIER 1 (Pattern)",
            "description": "Error logging command"
        },
        {
            "input": "play my favorite song",
            "expected_tier": "TIER 2 (LLM - Classify)",
            "description": "Unknown command - LLM to classify"
        },
        {
            "input": "good morning",
            "expected_tier": "TIER 1 (Pattern)",
            "description": "Greeting command"
        },
        {
            "input": "xyzabc foobar",
            "expected_tier": "TIER 2 (LLM - Fallback)",
            "description": "Gibberish - gives up"
        },
    ]
    
    print("=" * 80)
    print("LIVA TWO-TIER INTENT RECOGNITION TEST")
    print("=" * 80)
    
    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['description']}")
        print(f"Input: '{test['input']}'")
        print(f"Expected: {test['expected_tier']}")
        print("-" * 80)
        
        # Process the input
        result = router.handle_text(test['input'])
        
        # Display results
        print(f"Route:          {result['route'].upper()}")
        print(f"Intent:         {result['intent']}")
        print(f"Reason:         {result['routeReason']}")
        print(f"Response:       {result['ttsText']}")
        print(f"Command:        {result['commandText']}")
        print()


def explain_routing_logic():
    """Explain how the routing logic works."""
    
    print("\n" + "=" * 80)
    print("HOW THE TWO-TIER SYSTEM WORKS")
    print("=" * 80)
    
    explanation = """
1. TIER 1: Fast Pattern Matching (< 100ms)
   ─────────────────────────────────────────
   - Uses regex patterns in nlu/intent_parser.py
   - Examples of known intents:
     * "turn on/off the lights" → turn_on/off_device
     * "show last errors" → show_last_errors
     * "good morning" → good_morning
     * "what happened today" → what_happened_today
   
   - If a pattern matches → Execute immediately
   - No LLM involved → Super fast & reliable
   
   ✅ Pros: Fast, reliable, works offline
   ❌ Cons: Only handles pre-defined patterns

2. TIER 2: Smart LLM Fallback (1-3 seconds)
   ────────────────────────────────────────
   
   a) Question Detection:
      - Check if text ends with "?"
      - Check if starts with "what", "why", "how", etc.
      - If YES → Use LLM to answer the question
      
   b) Command Classification:
      - If NO pattern matched AND not a question
      - Use Ollama (qwen2.5:1.5b) to classify
      - LLM predicts the intent type
      - Examples: "play music", "set reminder", "adjust temperature"
      
   c) Fallback:
      - If LLM can't help → "I didn't understand that"
      
   ✅ Pros: Flexible, handles new/unknown intents
   ⚠️  Cons: Slower (1-3s), needs Ollama server

Key Decision Points:
──────────────────
1. Does it match a pattern? → Use TIER 1 (fast)
2. Is it a question? → Use LLM (smart)
3. Can LLM classify it? → Return the classification
4. Nothing worked? → "I didn't understand"

Performance Characteristics:
──────────────────────────
                 Latency    Reliability  Offline
TIER 1 (pattern) 50-150ms   100%         ✅ Yes
TIER 2 (LLM)     1-3s       80%          ❌ No
Fallback         100-200ms  N/A          ✅ Yes

Which Route is Used?
───────────────────
result['route'] values:
- "pattern"  → Matched via TIER 1 (fast regex)
- "llm"      → Classified by TIER 2 (Ollama)
- "none"     → Failed to classify (fallback)
"""
    print(explanation)


if __name__ == "__main__":
    print(__doc__)
    
    # Show explanation
    explain_routing_logic()
    
    # Run tests
    print("\n" + "=" * 80)
    print("Running test cases...")
    print("=" * 80)
    
    try:
        test_intent_routing()
    except Exception as e:
        print(f"\n❌ Error during testing: {e}")
        print("\nNote: Make sure Ollama is running on localhost:11434")
        print("  ollama serve")

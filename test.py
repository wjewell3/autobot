import time
import sys

# ── CONFIG ───────────────────────────────────────────────
MODEL  = "gpt-4o"               # must match model_name in config.yaml
BASE   = "http://localhost:4000" # LiteLLM proxy running locally
DELAY  = 0.05                   # seconds between counts
# ─────────────────────────────────────────────────────────

try:
    from openai import OpenAI
except ImportError:
    print("Run: pip install openai")
    sys.exit(1)

# Point at local LiteLLM proxy — no real API key needed
client = OpenAI(base_url=BASE, api_key="anything")

def think(messages: list[dict]) -> str:
    resp = client.chat.completions.create(model=MODEL, messages=messages)
    return resp.choices[0].message.content.strip()

def count_to_10():
    """Agent counts to 10 by asking the LLM for each number."""
    print("🤖 Bot starting task: count to 10 (via LLM)\n")
    history = [
        {"role": "system", "content": (
            "You are a counting agent. When given a number N, "
            "respond with ONLY the next number. Nothing else."
        )},
        {"role": "user", "content": "Start. Give me number 1."}
    ]
    current = think(history)
    print(f"  {current}", end="", flush=True)
    history.append({"role": "assistant", "content": current})

    for _ in range(9):
        history.append({"role": "user", "content": "Next number."})
        current = think(history)
        print(f"  {current}", end="", flush=True)
        history.append({"role": "assistant", "content": current})
        time.sleep(DELAY)

    print("\n\n✅ Done counting. Awaiting instructions...\n")

def await_instructions():
    """REPL — bot answers until you type exit."""
    history = [
        {"role": "system", "content": (
            "You are an autonomous AI bot. You just finished counting to 10. "
            "Await instructions from the operator and execute them helpfully. "
            "Be concise. If asked to do a task, do it step by step."
        )}
    ]
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Bot shutting down.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("🤖 Bot: Goodbye!")
            break

        history.append({"role": "user", "content": user_input})
        print("🤖 Bot: ", end="", flush=True)
        reply = think(history)
        print(reply)
        history.append({"role": "assistant", "content": reply})

if __name__ == "__main__":
    count_to_10()
    await_instructions()
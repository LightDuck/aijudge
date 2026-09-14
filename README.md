# AIJudge

AIJudge is a project that helps answer rules questions about the **Yu-Gi-Oh! Trading Card Game**.

Think of it like asking a knowledgeable friend, "Can I activate this card in response to that one?" or
"What happens if these two effects trigger at the same time?" — except instead of guessing, AIJudge looks
up the actual rules and official rulings before answering, and it always shows its sources.

## The core idea

Yu-Gi-Oh! rulings are notoriously tricky. A wrong answer that *sounds* confident is worse than no answer
at all — it can cost someone a game. So AIJudge is built around one guiding principle:

> **The computer decides. The AI explains.**

In other words, this project doesn't just ask an AI chatbot "what's the ruling?" and trust whatever it
says. Instead, wherever a question can be answered by a precise, repeatable rule (like "which effect
resolves first?"), that answer comes from carefully tested logic — not from an AI guessing. The AI's job is
to understand the question, fetch the right information, and explain the answer in plain language — never
to invent a ruling on its own.

If AIJudge can't find a confident, well-sourced answer, it's designed to say so and suggest asking a human
judge, rather than making something up.

## How an answer gets built

When it's finished, a typical question will flow through a few stages:

1. **Understand the question** — figure out which cards and rules are actually involved.
2. **Look things up** — pull the official card text, any official rulings on those cards, and relevant
   sections of the rulebook from a database, rather than relying on memory.
3. **Apply the rules** — for things like "which effect resolves first" or "can this card even be activated
   right now," use dedicated rules logic that always follows the game's actual procedures the same way
   every time.
4. **Explain the answer** — put it all together into a clear answer for the person asking, with the sources
   cited so they can double check it.

## What's already built vs. what's coming

This project is being built in stages, and it's currently a partial "thin slice" — some pieces are done,
others aren't wired up yet:

- ✅ **The rules logic** — the part that knows things like resolution order, whether a card can be
  activated in response to another, and whether a card's activation window has already passed.
- ✅ **The card and rulings database** — a place to store card text, official rulings, and rulebook
  sections so they can be looked up instead of guessed.
- ✅ **Reading card effects** — a way to break down a card's printed text into its condition, cost, and
  effect, with a review step to flag anything unclear.
- ✅ **Sample data** — a handful of well-known cards are already loaded in as examples.
- ✅ **Asking a question and getting an answer** — an API service wraps the rules logic and database behind
  HTTP endpoints, and a React chat interface (see "Running the frontend" below) talks to it, so the pieces
  above are now connected end-to-end from typing a question to getting a cited answer.
- ⏳ **Not yet built**: broader card coverage — only a handful of hand-picked cards are loaded in so far,
  not the full card pool.

## Why it's built this way

Yu-Gi-Oh! has thousands of cards and a rulebook full of edge cases. An AI language model on its own tends
to sound confident even when it's wrong, especially on obscure interactions. By having the *rules engine*
(precise, testable code) make the actual decisions, and only using AI for understanding language and
explaining results, AIJudge aims to be trustworthy rather than just plausible-sounding.

Every piece of logic is also built "test-first" — meaning a test describing the correct behavior is written
*before* the code that implements it. This matters a lot here: a bug in this project doesn't just crash a
program, it could mean giving someone the wrong ruling in a real game.

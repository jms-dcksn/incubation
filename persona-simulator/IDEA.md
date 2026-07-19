# Simulate Personas for Conversation Evals


Building on the core simulator example here: [text](../../multi-turn-evals)

This demo will give the user a simple interface to describe different personas, creating 1 to n personas in a dataset and then running all personas as a mass evaluation set against the LLM / agent - primarily using a trajectory evaluator for user satisfaction in MVP.

Use preferred stack:

- FastAPI backend
- Langchain create_agent with simple tools (account lookup, ticket history with seeded data from a simple db)
- Next.js
- Plan to deploy to Fly.io and Vercel

Results should show in a simple table - pass/fail from judge with aggregate scores in KPI cards at the top - overall pass rate as the main score.


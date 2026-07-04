# RLM exploration with Deep Agents

Explore **Recursive Language Models (RLMs)** and **dynamic subagents** in LangChain
[Deep Agents](https://github.com/langchain-ai/deepagents) using the QuickJS
**code interpreter middleware**.

Instead of the main model dispatching subagents one tool call at a time, the agent
writes a short JavaScript program that loops, branches, and fans out over
subagents (`task()`) inside a lightweight interpreter. That is the RLM idea in its
simplest form: an agent that writes code, and that code dispatches more agents.

Based on two LangChain blog posts:

- [Introducing Dynamic Subagents in Deep Agents](https://www.langchain.com/blog/introducing-dynamic-subagents-in-deep-agents)
- [How to Use RLMs in Deep Agents](https://www.langchain.com/blog/how-to-use-rlms-in-deep-agents)

See `README.md` for setup and `walkthroughs/` for a code walkthrough of every
example.

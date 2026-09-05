# Adversarial and red-team evals for a prior-authorization intake agent

Teaching material, not a product. A small LangChain ReAct agent classifies an
incoming prior-authorization request for downstream routing. Around it sits an
eval harness whose only job is to catch adversarial inputs: prompt injection,
authority spoofing, tool abuse, PHI exfiltration, prompt extraction, obfuscated
payloads, and output hijacking.

The point of the folder is the contrast. The same 16 cases run against three
configurations: a hardened prompt, a naive prompt, and the naive prompt behind a
LangChain middleware enforcement layer. The harness scores all three, and the
numbers show what prompting buys, what enforcement buys, and what neither fixes.

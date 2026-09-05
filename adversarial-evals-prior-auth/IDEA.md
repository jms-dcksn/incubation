# Adversarial and red-team evals for a prior-authorization intake agent

Teaching material, not a product. A small LangChain ReAct agent classifies an
incoming prior-authorization request for downstream routing. Around it sits an
eval harness whose only job is to catch adversarial inputs: prompt injection,
authority spoofing, tool abuse, PHI exfiltration, prompt extraction, obfuscated
payloads, and output hijacking.

The point of the folder is the contrast. The same 14 cases run against a
hardened prompt and a naive prompt. The harness scores both, and the numbers
show what the defenses buy and what the eval catches.

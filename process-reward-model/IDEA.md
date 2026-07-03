# Process Reward Models for Non-Verifiable Domains

This project explores process reward models (PRMs) for AI agents operating in domains where the final outcome can't be automatically verified (no unit tests, no ground-truth answer, no scalar reward). Instead of scoring only the final answer, we score the *process* by which the agent arrived at it.

The core mechanism is an online trajectory evaluator: as the agent works, a judge (model or rubric-driven) scores the reasoning steps, tool calls, and intermediate decisions along the way, rewarding good process even when we can't cheaply verify the end result.

A promising variant is pairwise trajectory evaluation - instead of scoring a trajectory in isolation, compare the agent's process against how a subject matter expert (SME) would execute the same task, and reward alignment with expert process/judgement rather than just the final output.

## Topics

- Online trajectory evaluators that score reasoning/tool-use steps as they happen, not just the final output
- Pairwise comparison: agent trajectory vs. SME trajectory for the same task
- Building rubrics/critiques for "good process" in domains without verifiable rewards (writing, research, judgment calls, open-ended coding)
- Capturing SME traces (screen recordings, tool logs, think-alouds) as reference trajectories
- Using process rewards as a training signal (RLHF/RLAIF-style) vs. as a runtime monitor/guardrail
- Failure modes: reward hacking the process critique, judge drift, expensive/slow online evaluation
- Where this complements vs. replaces outcome-based reward models

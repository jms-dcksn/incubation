# Human driven evals

You have an agent built - now what?

Creating a great eval set is important, but hard.

How can I anticipate all the ways this agent could fail? What is a good representative distribution of input data to stimulate this agent? Will it get off track during the run? Will it confidently provide an incorrect answer? Will it end a conversation too early? How will it handle tool call failures?

The questions go on forever. THe very nature of LLMs provides such a wide surface of possible failure modes - many of which will only emerge in production. In many cases it isn't practical or possible to build the perfect dataset for evals. 

So how do we mitigate the risk of creating a poor experience for users? 

Most evaluation frameworks steer you to building an LLM judge, using code/heuristics, or using an agent to analyse traces to find failure modes and inform a judge build. 

All of these approaches fall short - great evals start with human intuition that maps the intent of the agent to possible application failures. Great data and insights comes from looking at real agent runs, and leveraging that human intuition to find the common failure modes, characterize those against the intent of the application. Evaluators should be built from the combination of intuition, insight and data for thorough definition.

This project will be a demo of an evaluation harness that is human-first. 

The lifecycle is:

- Build a dataset
- Run the agent across the dataset
- Manual labelling of that dataset
- Analysis agent asynchronously review human labels and begins building evaluators
- Once a threshold of labelled data is crossed, evaluators are recommended to user
- Evaluators are run on original dataset and verified against labels for human alignment
- mis-alignment drives an improvement loop
- Once alignment crosses threshold, evaluators are recommended as sufficiently capable



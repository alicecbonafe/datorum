Explanation
===========

Research in artificial intelligence is only just beginning to address the effects of
context on content generation by large transformer-based language models. There is
already solid evidence that using contexts larger than those employed during model
training leads to a loss of information presented in the middle of the prompt [Liu24]_.
We also have some understanding of how large models can be easily distracted by
irrelevant information within the context [Shi23]_. This field of study has only
continued to expand since then.

When we consider the applicability of these findings in real-world contexts, we cannot
ignore the economic and environmental costs that artificial intelligence has imposed on
contemporary society. Continuously increasing the capabilities of models, aiming to
overcome these context limitations, may make sense when we talk about the cutting edge
of scientific research, but the everyday use of this technology must be more rational
to be sustainable, both from an economic and environmental point of view.

This is the focus of Datorum: to be a framework for creating AI agents and pipelines,
with a strong emphasis on context curation to improve the accuracy of complex
inferences, reducing token consumption for handling irrelevant contexts. Datorum's
design principles include context flexibility and mappability (including chat history),
transparency in tool usage, multi-model agency, and a strong presence of HITL.

.. [Liu24] Liu, N. et al. (2024). Lost in the Middle: How Language Models Use Long
   Contexts. *TACL*, 12, 157-173.

.. [Shi23] Shi, F. et al. (2023). Large Language Models Can Be Easily
   Distracted by Irrelevant Context. *ICML 2023*.

.. toctree::
   :maxdepth: 1

   core-concepts

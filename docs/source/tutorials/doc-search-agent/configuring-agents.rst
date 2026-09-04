==================
Configuring agents
==================

In this chapter, we'll configure LMStudio as our inference provider. Then, we'll
create a basic agent role and test it with the doc search toolbox. Finally, we'll
create two roles to be used in the pipeline.

Inference provider
==================

This is how a provider definition should look like within the CLI settings file.

.. code-block:: yaml

    agencykit:
      providers:
        lmstudio:
          id: lmstudio
          description: Local LMStudio provider.
          base_url: http://localhost:1234/v1
          api_key_selector: null
          supports_streaming: true
          models:
          - deepseek/deepseek-r1-0528-qwen3-8b
          - olmo-3-7b-instruct
          - mistralai/ministral-3-3b


Note that when ``api_key_selector`` is ``null``, the API key will be retrieved
using the provider's ID field. This selector is used when calling the ``api_key``
resource factory.

The default behavior here is to use a env var called ``LMSTUDIO_API_KEY``, but
this can be easily customized. For this tutorial, it's enough to create a dictionary
for ``api_keys``, in the settings file:

.. code-block:: yaml
    api_keys:
      lmstudio: lmstudio

If you need a more specific behavior, you can declare a function in a custom registry
Python code, decorating it with ``@datorum.resource("api_key")``. The function must
receive one string parameter (the selector) and return a string (the API key), and the
Python code must be in the ``custom_registry`` list of the CLI settings file.

Basic agent role
================

For alpha-2, we cannot customize toolbox setup bindings in command line. Instead,
we'll need a new toolbox setup.

.. code-block:: yaml

    toolkit:
      toolboxes:
        rfc_search:
          # ...
        rfc_search_basic:
          id: rfc_search_basic
          toolbox_name: doc_search
          tools_enabled:
          - keyword_search
          - regex_search
          context_bindings:
          - field_id: domain
            binded_id: quirky_tech_specs
            context: files
            context_bind_type: domain-path
            local: false
          - field_id: interactive
            binded_id: tool-selection  # <-- custom bind here
            context: docs
            context_bind_type: model-input
            local: true
          resource_bindings: []

A testable agent should be able to decide whether to use tools. Also, we do not need
``system_instructions``, since it'll be in the chat history. This field is meant to
be used by context builders to change the chat history between agent calls.

.. code-block:: yaml
    agencykit:
      providers:
        # provider definition
      roles:
        basic:
          id: basic
          description: A testable agent.
          preferred_models:
          - mistralai/ministral-3-3b
          tools_enabled:
          - rfc_search_basic.keyword_search
          - rfc_search_basic.regex_search
          tool_choice: auto
          tool_max_iter: 3

Now, let's prepare a chat history for this run. I'll save it as ``shared/docs/chat-basic.yaml``.

.. literalinclude:: /examples/doc-search-agent/shared/docs/chat-base.yaml
    :language: yaml

Remember to link it.

.. code-block:: bash
    datorum config context link docs shared/docs/chat-basic.yaml -t application/yaml -m chat-history

Now, let's give it a try, always referring to the chat history as local, using the
underscore prefix, unless we want the original file to be changed. At this point,
LMStudio should be up and running.

.. code-block:: bash
    datorum run agent basic _docs:chat-basic

The local context will be created in ``local/agent_<timestamp>`` and there you'll
find the ``docs/chat-basic.yaml`` with all the tool calls and the final answer. In
this file, you can verify how the model used the tools. Testing multiple models will
lead you to the better combination between tool signature + docs and the model.

Pipeline agent roles
====================

Now, let's split the responsibilities so that, within the pipeline, one role calls
the tools while another provides the final answer.

.. code-block:: yaml

    agencykit:
      providers:
        # provider definition
      roles:
        basic:
          # basic role definition
        searcher:
          id: searcher
          preferred_models:
          - mistralai/ministral-3-3b
          system_instructions: Use tools to find lines matching the user's request in
              the enabled files.
          temperature: 0.4
          tools_enabled:
          - doc_search.keyword_search
          - doc_search.regex_search
          tool_choice: required
          tool_max_iter: 3
        answerer:
          id: answerer
          preferred_models:
          - olmo-3-7b-instruct
          system_instructions: Answer the user's question using the conversation so far,
              which may include search results gathered earlier in this session. Cite the
              source filename for any claim drawn from a search result.
          temperature: 0.8
          top_p: 0.8

Notice that here we have ``system_instructions`` for both roles. In order to use them,
we need to create some context building tools.
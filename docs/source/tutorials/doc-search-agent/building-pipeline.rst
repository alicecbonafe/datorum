Building the pipeline
=====================

Now that tools and agents are ready, let's assemble the pipeline. We'll need
these steps:

* **List files** (tool): read searchable files in the domain and prepare
    the markdown.
* **Edit selection** (human): wait for the user to edit the markdown, selecting
    files and writing the question.
* **Build chat history** (tool): prepare the chat history document according to
    the context.
* **Check selection** (decision): check the tool response to decide which agent
    to call.
* **Search first** (agent): first agent role, forced to use the search tools.
* **Final inference** (agent): second agent role, no tools available.
* **Extract answer** (tool): append the assistant message to the markdown.

While a hypothetical end-user could limit all their interactions to Markdown, it
is possible to review the chat history to see how each agent behaved, allowing
for further adjustments.

Pipeline steps
==============

Tool steps should be configured like this:

.. code-block:: yaml

    plumbingkit:
      pipelines:
        doc-search-agent:
          id: doc-search-agent
          steps:
            list-files:
              type: tool
              id: list-files
              target_id: edit-selection
              description: Read searchable files in the domain and prepare
                the markdown.
              tool_params:
                field_id: tool_params
                binded_id: empty
                context: docs
              tool_result:
                field_id: tool_result
                binded_id: tool_response
                context: docs
                local: true
              toolbox_setup:
                field_id: toolbox_setup
                factory_name: toolbox_setup
                selector: context_builder.scaffold_selection

In human interaction steps, the ``interactive`` binding is not directly used
by the worker. Instead, the CLI prints out the path and waits for user to edit
it.

.. code-block:: yaml

    edit-selection:
      type: human
      id: edit-selection
      target_id: build-history
      description: wait for the user to edit the markdown, selecting
        files and writing the question.
      interactive:
        field_id: interactive
        binded_id: selection
        context: docs
        local: true

Decision steps use an input data binding and a small piece code to determine
the next target.

.. code-block:: yaml

    check-selection:
      type: decision
      id: check-selection
      description: Check the tool response to decide which agent
        to call.
      target_options:
      - search-first
      - final-inference
      code_type: formula
      code: '''search-first'' if int(input_data["count"]) > 0 else ''final-inference'''
      input_data:
        field_id: input_data
        binded_id: tool_response
        context: docs
        local: true

An agent step should define a chat history, an inference provider and an
agent role.

.. code-block:: yaml

    search-first:
      type: agent
      id: search-first
      target_id: build-history
      description: First agent role, forced to use the search tools.
      chat_history:
        field_id: chat_history
        binded_id: chat
        context: docs
        local: true
      inference_provider:
        field_id: inference_provider
        factory_name: inference_provider
        selector: lmstudio
      agent_role:
        field_id: agent_role
        factory_name: agent_role
        selector: searcher

The pipeline flow will start at the step defined in the ``first_step_id`` pipeline's field
and will end whenever it finds a step whose ``target_id`` field is null.

See the :download:`complete settings here </examples/doc-search-agent/.datorum.yml>`.

Creating and running flows
==========================

Pipelines run in flows. Each flow holds a copy of the pipeline, so it's possible to customize
the pipeline for a specific flow, without impacting others. It also helps to keep track of
each flow. Here's how to create the flow without running it:

.. code-block:: bash

    datorum run pipeline --pipeline doc-search-agent --create-only

The pipeline flow settings will be placed in the ``flows_path`` defined in the CLI settings.
To run the created flow, supposing you just created ``flow_0``:

.. code-block:: bash

    datorum run pipeline flow_0

The command above can also be used to resume an interrupted or crashed pipeline, since flow
state is stored within its settings.

You can also create and run the flow in a single command, just by omitting the
``--create-only`` flag:

.. code-block:: bash

    datorum run pipeline --pipeline doc-search-agent

The local context for a pipeline flow is stored with the flow ID, such as in
``local/flow_0/docs/selection.md``.

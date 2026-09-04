===============================
Implementing doc search toolbox
===============================

For this tutorial we'll create two simple search tools, one for keyword
search and another for regex search. A semantic search could follow a
similar path. We start declaring how the toolbox binds to the context.

Bindable fields
===============

The search tools need to know which files the user selected in the markdown
frontmatter. Also, they need the path for the directory we already mapped as
a domain.

.. code-block:: python

    from pathlib import Path
    import datorum

    @datorum.toolbox(name="doc_search")
    class DocSearchToolbox:

        domain: Path | None = datorum.ContextField(
            context_bind_type="domain-path",
            required=True,
        )
        interactive: datorum.MarkdownDocument | None = datorum.ContextField(
            context_bind_type="model-input",
            required=True,
        )

A context field declared as "domain-path" will only set the attribute with
the domain path, and saves nothing afterwards. In the case of a "model"
binding, it would save the document after each tool run, unless we use the
"-input" prefix.

Tool declarations
=================

When we want an agent to use a tool, we need to exercise some care. The
method signature itself leads the agent to draw conclusions. For instance,
declaring a tool simply as `search` leads the model to conclude that it
involves a semantic search. Argument names, as well as the docstring, also
require attention in this regard.

.. code-block:: python

    @datorum.toolbox(name="doc_search")
    class DocSearchToolbox:

        # (bindable fields)

        @datorum.tool()
        def keyword_search(self, keywords: list[str], case_sensitive: bool = False) -> dict[str, Any]:
            """Find text containing any of the given plain-text keywords or phrases.

            Use this for most searches. Pass whole or short phrases exactly as
            they're expected to appear in the text. Since regex and wildcards are
            not recognized, nothing needs escaping.

            Example: keyword_search(keywords=["refund policy", "return window"])

            :param keywords: A list with one or more literal words/phrases to look for.
                Only files containing at least on of these keywords will be included in
                the results.
            :type keywords: list[str]
            :param case_sensitive: If False (default), matching ignores case.
            :type case_sensitive: bool
            """
            ...

        @datorum.tool()
        def regex_search(self, patterns: list[str], case_sensitive: bool = False) -> dict[str, Any]:
            """Find text matching any of the given regular expressions.

            Only use this when keyword_search isn't precise enough -- e.g. to
            match a numeric range or a word boundary.

            Example: regex_search(patterns=["error code \\d+", "failed with status])

            :param patterns: A list with one or more regex patterns to look for.
                Only files matching at least on of these patterns will be included in
                the results.
            :type patterns: list[str]
            :param case_sensitive: If False (default), matching ignores case.
            :type case_sensitive: bool
            """
            ...

See the :download:`full implementation here </examples/doc-search-agent/doc_search_toolbox.py>`.

Configuring
===========

In the ``.datorum.yml`` file, two steps are necessary. Let's start by creating the
toolbox settings, where we can pre bind the fields we already have.

.. code-block:: yaml

    toolkit:
      toolboxes:
        rfc_search:
          id: rfc_search
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
            binded_id: selection
            context: docs
            context_bind_type: model-input
            local: true

Note that ``domain`` is not local, because the searchable files are in the shared
context. On the other hand, ``interactive`` is local, because it will be different
for each pipeline run.

We also need to add the toolbox implementation to the ``custom_registry`` at the end
of the CLI settings.

.. code-block:: yaml

    custom_registry:
    - doc_search_toolbox.py

Testing
=======

When an agent uses a tool, its parameters and response are automatically binded
to the chat history. Calling a tool directly requires us to create both documents.

The parameters file would look like these:

.. literalinclude:: /examples/doc-search-agent/shared/docs/keyword-search-params.yaml
    :language: yaml

.. literalinclude:: /examples/doc-search-agent/shared/docs/regex-search-params.yaml
    :language: yaml

The results file is just an empty dict:

.. literalinclude:: /examples/doc-search-agent/shared/docs/search-result.yaml
    :language: yaml

The interactive document needs to hold a list of files, so let's make a copy and
link all files to the context.

.. code-block:: bash

    cp shared/docs/selection.md shared/docs/tool-selection.md
    datorum config context link docs shared/docs/keyword-search-params.yaml -t application/yaml -m dict
    datorum config context link docs shared/docs/regex-search-params.yaml -t application/yaml -m dict
    datorum config context link docs shared/docs/search-result.yaml -t application/yaml -m dict
    datorum config context link docs shared/docs/tool-selection.md -t text/markdown -m markdown

Remember to enable some search files in the new markdown.

.. literalinclude:: /examples/doc-search-agent/shared/docs/tool-selection.md
    :language: markdown

When running a tool, generally we'll want to use a copy of the search result document
in the tool's local context, so the shared document remains unchanged. In the command
line, it is done adding an underscore (``_``) before the binding declaration.

.. code-block:: bash

    datorum run tool rfc_search.keyword_search docs:keyword-search-params _docs:search-result --bind-context "interactive=model-input(docs:tool-selection)"

In the terminal, you will see the broadcasted messages. Messages starting with
``[UPDATE]`` are job status updates. This prefix is followed by the new status,
such as ``[working]`` or ``[finished]``. Unless you see a ``[crashed]`` update,
at this point you should have the ``local`` directory created, with a sub
directory starting with "tool\_" followed by the current timestamp. This is the
tool's local context, where lives all local copies of shared context documents.
Take a look at ``docs/search-result.yaml``, it should look like this:

.. code-block:: yaml
    total_matches: 2
    files_matched:
    - rfc1925.txt
    - rfc2549.txt
    results:
      rfc1925.txt:
      - "e it slower, but it won't make it happen any\n             quicker.\n\n\n\n\n\
        \nCallon                       Informational                      [Page 1]\n\f\
        \nRFC 1925            Fundamental Truths of Networking        1 April 1996\n\n\
        \n   (3)  With sufficient thrust, pigs fly just fine. However, this is\n     \
        \   not necessarily a good idea. It is hard to be sure where they\n        are\
        \ going to land, and it could be dangerous sitting under them\n        as they\
        \ fly overhead.\n\n   (4)  Some things in life can never be fully a"
      rfc2549.txt:
      - "pecification.  These words are often capitalized.\n\n   MUST      Usually.\n\n\
        \   MUST NOT  Usually not.\n\n   SHOULD    Only when Marketing insists.\n\n  \
        \ MAY       Only if it doesn't cost extra.\n\nSecurity Considerations\n\n   There\
        \ are privacy issues with stool pigeons.\n\n   Agoraphobic carriers are very insecure\
        \ in operation.\n\nPatent Considerations\n\n   There is ongoing litigation about\
        \ which is the prior art: carrier or\n   egg.\n\nReferences\n\n   Waitzman, D.,\
        \ \"A Standard for the Transmission of IP Datagrams on\n   Avia"
    query:
    - pigeon
    - pigs

Same thing for the regex search:

.. code-block:: bash

    datorum run tool rfc_search.regex_search docs:regex-search-params _docs:search-result --bind-context "interactive=model-input(docs:tool-selection)"

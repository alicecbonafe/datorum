================
Creating context
================

Shared context lives in the ``shared`` directory and we are going to use
``docs`` as the domain for these documents, so we'll create them in the
``shared/docs`` directory.

.. code-block:: bash

   mkdir -p shared/docs
   datorum config context create docs

Pipeline documents
==================

This pipeline is expected to interact with the user thru a markdown file
and with the models thru a chat-history file. We are going to need tools
for context building and for file searching. The first group do not need
parameters, the files will be binded as attributes, and returns a simple
``dict``, that will be read by a decision step to define which agent to
use for each chat built.

.. note::
   In this version, a params document is required even without arguments
   in the method signature. This will change in future versions.

Creating documents
------------------

* File selection markdown (HITL interactive document -- ``selection.md``)
* Chat history (``chat.yaml``)
* An empty params file (``empty.txt``)
* A dict document holding the context builder results (``tool-response.yaml``)

For the ``shared/docs/selection.md``, just a placeholder for selectable files and user's
question is enough.

.. literalinclude:: /examples/doc-search-agent/shared/docs/selection.md
   :language: python

The other files are simpler and can be created using command line.

.. code-block:: bash

   touch shared/docs/empty.txt
   echo 'messages: []' > shared/docs/chat.yaml
   echo '{}' > shared/docs/tool-response.yaml

Linking documents
-----------------

To use this files as Python object in the pipeline, they need to be in the
CLI context. This can be done with these commands:

.. code-block:: bash

   datorum config context link docs shared/docs/chat.yaml -t application/yaml -m chat-history
   datorum config context link docs shared/docs/selection.md -t text/markdown -m markdown
   datorum config context link docs shared/docs/empty.txt
   datorum config context link docs shared/docs/tool-response.yaml -t application/yaml -m dict

Sample files
============

Finally, we are going do download some sample files for the model to search in.
For that, we are going to use the "Quirky Tech Specs" collection (IETF April
Fools RFCs) for this tutorial. First, let's create a separeated context for that.

.. code-block:: bash

   mkdir -p shared/files/quirky_tech_specs
   datorum config context create files

Now, we are going to download  a handful of files.

.. code-block:: bash

   # HTCPCP (Coffee Pot Protocol)
   curl -O --output-dir shared/files/quirky_tech_specs https://www.rfc-editor.org/rfc/rfc2324.txt
   # IP over Avian Carriers (Carrier Pigeons)
   curl -O --output-dir shared/files/quirky_tech_specs https://www.rfc-editor.org/rfc/rfc1149.txt
   # The Evil Bit (IPv4 Security Flag)
   curl -O --output-dir shared/files/quirky_tech_specs https://www.rfc-editor.org/rfc/rfc3514.txt
   # The 12 Networking Truths
   curl -O --output-dir shared/files/quirky_tech_specs https://www.rfc-editor.org/rfc/rfc1925.txt
   # Avian Carriers with Quality of Service
   curl -O --output-dir shared/files/quirky_tech_specs https://www.rfc-editor.org/rfc/rfc2549.txt

If you want a larger base to play with, you can download it like this:

.. code-block:: bash

   for rfc in 1313 1437 1438 1605 1606 1607 1926 1927 2100 2325 2795 3093 3251 4824 6214; do
     curl -O --output-dir shared/files/quirky_tech_specs "https://www.rfc-editor.org/rfc/rfc${rfc}.txt"
   done

Search domain
-------------

In order to search these files, Datorum needs to map the directory as a domain.
If you take a look at the generated ``.datorum.yml`` file, right now, it should
look like this:

.. code-block:: yaml

    shared_context_path: shared
    local_context_path: local
    flows_path: flows
    flow_id_template: flow_{index}
    toolkit:
      toolboxes: {}
    agencykit:
      providers: {}
      roles: {}
    plumbingkit:
      pipelines: {}
    shared_context:
      docs:
        id: docs
        documents:
          chat:
            id: chat
            doc_type: application/yaml
            doc_model: chat-history
            extension: yaml
            metadata: {}
          selection:
            id: selection
            doc_type: text/markdown
            doc_model: markdown
            extension: md
            metadata: {}
          empty:
            id: empty
            doc_type: text/plain
            doc_model: text
            extension: txt
            metadata: {}
          tool-response:
            id: tool-response
            doc_type: application/yaml
            doc_model: dict
            extension: yaml
            metadata: {}
        domain_metadata: {}
      files:
        id: files
        documents: {}
        domain_metadata: {}
    custom_registry: []
    api_keys: null

As you can see, the shared context called ``docs`` holds references for all the
documents we created and linked. There's also the shared context called ``files``,
with no documents. For the downloaded files to be searchable, we do not need them
mapped as documents, just create an empty dict as the domain metadata, so Datorum
know it exists.

.. code-block:: yaml

    # (...)
      files:
      id: files
      documents: {}
      domain_metadata:
        quirky_tech_specs: {}
    # (...)

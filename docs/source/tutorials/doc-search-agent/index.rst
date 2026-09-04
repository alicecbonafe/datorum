================
Doc Search Agent
================

This tutorial demonstrates how to create an agent pipeline with a customized
toolbox, human-in-the-loop and multi-model inference.

Using a markdown file to interact with the human-user, this pipeline presents
a list of searchable files in the frontmatter. The user then selects which
files should be available for searching in the frontmatter and writes the
question in the markdown body. Then, a first model makes the searches and
a second model answers the question. The generated answer is then extracted
and appended to the markdown body. This tutorial uses LMStudio as inference
provider.

Before you start, please make sure to install Datorum using PyPI.
You can create a Python virtual env to isolate dependencies.

.. code-block:: bash

   python -m venv venv
   source ./venv/bin/activate
   pip install datorum

Then, go to your workspace dir and start the CLI's config file.

.. code-block:: bash

   cd /path/to/workspace
   datorum config init

This should create a file named ``.datorum.yml`` with this content:

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
   shared_context: {}
   custom_registry: []
   api_keys: null

Chapters
--------

.. toctree::
   :maxdepth: 1

   creating-context
   implementing-doc-search
   configuring-agents
   implementing-context-builder
   building-pipeline

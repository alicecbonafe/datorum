===========================
Built-in resource factories
===========================

A resource factory is a callable registered under a name, resolved via a
:py:class:`~datorum.ResourceBind`'s ``factory_name``. Datorum's built-in
factories aren't all available unconditionally -- most are registered by a
specific Worker's constructor, so they only exist once you've built that
Worker. This page catalogs the ones shipped in ``src/datorum``.

============================ ============================================ ============================================================ ==============================================================
Factory name                 Registered by                                Selector                                                     Notes
============================ ============================================ ============================================================ ==============================================================
``toolbox_setup``            ``ToolWorker.__init__``                      ``"SETUP_ID.TOOL_NAME"``                                     Returns the named :py:class:`~datorum.ToolBoxSetUp` with
                                                                                                                                         ``active_tool`` set to ``TOOL_NAME``. Raises if the selector
                                                                                                                                         isn't ``x.y``-shaped or ``SETUP_ID`` isn't in the
                                                                                                                                         ``ToolWorker``'s ``ToolKit``.
``inference_provider``       ``AgentWorker.__init__``                     Provider ID (key in ``AgencyKit.providers``)                 Required on a job (no selector -> error). Not automatically
                                                                                                                                        used as a fallback inside a pipeline -- see below.
``agent_role``               ``AgentWorker.__init__``                     Role ID (key in ``AgencyKit.roles``)                         Required on a job.
``api_key``                  ``register_mapped_api_key_factory()`` --     Env var name (or ``InferenceServiceProvider.id`` if the      **Opt-in**: not registered automatically anywhere. An
                              **not automatic**, an app must call this      provider sets no ``api_key_selector``)                       application has to call this explicitly during setup. Reads
                              during setup                                                                                               from ``os.environ`` by default; a different ``source``
                                                                                                                                         mapping, a key-name regex, and a formatter callback can all
                                                                                                                                         be supplied.
``create_pipeflow``          ``PipelineWorker.register_flow_factories()`` Pipeline ID (key in ``PlumbingKit.pipelines``)               **Opt-in**: only registered if the application calls
                              -- also opt-in                                                                                             ``register_flow_factories(flow_path, ...)`` on its
                                                                                                                                         ``PipelineWorker``. Creates a new persisted ``PipeFlow`` on
                                                                                                                                         disk under ``flow_path``.
``restore_pipeflow``         ``PipelineWorker.register_flow_factories()`` Flow ID (e.g. ``flow_0``)                                    Same opt-in call as above. Restores a previously saved
                                                                                                                                         ``PipeFlow`` from disk, or from an in-memory cache if it's
                                                                                                                                         already active.
============================ ============================================ ============================================================ ==============================================================

Registering your own
-----------------------

Use :py:func:`~datorum.register_resource_factory` (or the
``@datorum.resource(name=...)`` decorator) to add a factory of your own.
Both validate the callable's signature: exactly one required positional
parameter, no ``*args``/``**kwargs``, and if the parameter is annotated, the
annotation must accept ``str | None``.

Why ``inference_provider`` has no pipeline-level fallback
--------------------------------------------------------------

``AgentWorker.work`` *can* fall back to ``get_preferred_provider(role.
preferred_models)`` when no ``inference_provider`` resource binding is
present in the job at all. In practice that path is unreachable from a
``PlumbingKit`` pipeline: ``AgentStep.inference_provider`` is a required
field with no default, so ``PipelineWorker`` always includes some binding
for it in the delegated job -- even an empty/invalid one would count as
"present" and skip the fallback, then fail when resolved. The fallback only
fires for jobs assembled some other way, e.g. by a CLI command that omits a
``-p`` flag. Inside a pipeline, always name the provider explicitly.
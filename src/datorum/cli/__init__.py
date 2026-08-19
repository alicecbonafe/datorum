"""
Suggested by Claude:

src/datorum/cli/
├── __init__.py       # exposes `cli`
├── app.py            # root click group + lazy settings loading
├── settings.py        # AppSettings (fixed)
├── bindings.py         # "field=type(selector)" parsing grammar
├── context.py           # wires Binder + all *Worker instances together
├── runner.py             # asyncio.run + broadcaster→stdout loop
├── errors.py              # DatorumBaseError → click.ClickException
├── validate.py             # cross-reference checks
└── commands/
    ├── __init__.py
    ├── init_config.py
    ├── kits.py            # export/import groups
    ├── tool.py
    ├── agent.py
    ├── flow.py
    └── validate.py         # thin click wrapper around ../validate.py
"""
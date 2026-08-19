from pathlib import Path
import re

import datorum

from .settings import CliAppSettings


class CliAppContext:

    def __init__(self, settings_path: Path):
        self.settings = CliAppSettings()
        self.settings.settings_path = settings_path

        self._binder: datorum.Binder | None = None
        self._tool_worker: datorum.ToolWorker | None = None
        self._agent_worker: datorum.AgentWorker | None = None
        self._pipeline_worker: datorum.PipelineWorker | None = None

    @property
    def binder(self):
        if not self._binder:
            self.settings.load()
            self._create_binder()
        return self._binder

    @property
    def tool_worker(self) -> datorum.ToolWorker:
        if not self._tool_worker:
            self._tool_worker = datorum.ToolWorker(
                binder=self.binder,
                toolkit=self.settings.toolkit,
            )
        return self._tool_worker

    @property
    def agent_worker(self) -> datorum.AgentWorker:
        if not self._agent_worker:
            self._agent_worker = datorum.AgentWorker(
                binder=self.binder,
                agencykit=self.settings.agencykit,
                tool_worker=self.tool_worker,
            )
        return self._agent_worker

    @property
    def pipeline_worker(self) -> datorum.PipelineWorker:
        if not self._pipeline_worker:
            self._pipeline_worker = datorum.PipelineWorker(
                binder=self.binder,
                plumbingkit=self.settings.plumbingkit,
                agent_worker=self.agent_worker,
                tool_worker=self.tool_worker,
            )
        return self._pipeline_worker

    def _create_binder(self) -> datorum.Binder:
        self._binder = datorum.Binder()

        for ctx in self.settings.contexts.values():
            self._binder.add_context(context=ctx)

        try:
            datorum.get_resource_factory("api_key")
        except datorum.ResourceFactoryError:
            if self.settings.api_keys is None:
                datorum.register_mapped_api_key_factory(
                    key_name_formatter=lambda k: f"{str.upper(k)}_API_KEY",
                    binder=self._binder,
                )
            else:
                datorum.register_mapped_api_key_factory(
                    self.settings.api_keys,
                    binder=self._binder,
                )

        last_index: int = -1
        prefix, suffix = self.settings.flow_id_template.split("{index}")
        flow_id_re_str = re.escape(prefix) + r"(\d+)" + re.escape(suffix)
        flow_id_re = re.compile(self.settings.flow_id_template)

        for flow_id in self.settings.flows.keys():
            match = flow_id_re.fullmatch(flow_id)
            if match:
                last_index = max(int(match.group(1)), last_index)

        @self._binder.resource(name="create_pipeflow", force=True)
        def _create_pipeflow(pipeline_id) -> datorum.PipeFlow:
            nonlocal last_index

            if not pipeline_id:
                raise datorum.PipelineWorkerError("Pipeline ID is required")
            if pipeline_id not in self.settings.plumbingkit.pipelines:
                raise datorum.PipelineWorkerError(f"Pipeline '{pipeline_id}' not found")
            pipeline: datorum.Pipeline = self.settings.plumbingkit.pipelines[pipeline_id]

            index = last_index + 1
            flow_id = self.settings.flow_id_template.format(index=index)
            flow_file = (self.settings.flows_path / flow_id).with_suffix(".yml")

            while flow_file.exists():
                index += 1
                flow_id = self.settings.flow_id_template.format(index=index)
                flow_file = (flow_path / flow_id).with_suffix(".yml")

            last_index = index
            flow_files[flow_id] = flow_file

            pipeline_copy: datorum.Pipeline = datorum.Pipeline.model_validate(
                pipeline.model_dump(mode="python")
            )
            pipeflow: datorum.PipeFlow = datorum.PipeFlow(
                id=flow_id,
                pipeline=pipeline_copy,
            )
            pipeflow.save_as(flow_file)
            return pipeflow

        @self._binder.resource(name="restore_pipeflow", force=True)
        def _restore_pipeflow(flow_id) -> datorum.PipeFlow:
            if not flow_id:
                raise datorum.PipelineWorkerError("Pipeflow ID is required")

            if flow_id not in self.settings.flows:
                flow_file = (flow_path / flow_id).with_suffix(".yml")
                if not flow_file.exists():
                    raise datorum.PipelineWorkerError(f"Pipeflow '{flow_id}' not found")
                self.settings.flows[flow_id] = flow_file

            return datorum.PipeFlow.load(self.settings.flows[flow_id])


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

        for ctx in self.app_settings.contexts.values():
            self._binder.add_context(context=ctx)

        try:
            datorum.get_resource_factory("api_key")
        except datorum.ResourceFactoryError:
            if self.app_settings.api_keys is None:
                datorum.register_mapped_api_key_factory(
                    key_name_formatter=lambda k: f"{str.upper(f)}_API_KEY",
                    binder=self._binder,
                )
            else:
                datorum.register_mapped_api_key_factory(
                    self.app_settings.api_keys,
                    binder=self._binder,
                )

        last_index: int = -1
        prefix, suffix = flow_id_template.split("{index}")
        flow_id_re_str = re.escape(prefix) + r"(\d+)" + re.escape(suffix)
        flow_id_re = re.compile(flow_file_re_str)

        for flow_id in self.app_settings.flows.keys():
            match = flow_id_re.fullmatch(flow_id)
            if match:
                last_index = max(int(match.group(1)), last_index)

        @self._binder.resource(name="create_pipeflow", force=True)
        def _create_pipeflow(pipeline_id) -> datorum.PipeFlow:
            nonlocal last_index

            if not pipeline_id:
                raise PipelineWorkerError("Pipeline ID is required")
            if pipeline_id not in self.app_settings.plumbingkit.pipelines:
                raise PipelineWorkerError(f"Pipeline '{pipeline_id}' not found")
            pipeline: Pipeline = self.app_settings.plumbingkit.pipelines[pipeline_id]

            index = last_index + 1
            flow_id = flow_id_template.format(index=index)
            flow_file = (self.app_settings.flows_path / flow_id).with_suffix(".yml")

            while flow_file.exists():
                index += 1
                flow_id = flow_id_template.format(index=index)
                flow_file = (flow_path / flow_id).with_suffix(".yml")

            last_index = index
            flow_files[flow_id] = flow_file

            pipeline_copy: Pipeline = Pipeline.model_validate(
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
                raise PipelineWorkerError("Pipeflow ID is required")

            if flow_id not in self.app_settings.flows:
                flow_file = (flow_path / flow_id).with_suffix(".yml")
                if not flow_file.exists():
                    raise PipelineWorkerError(f"Pipeflow '{flow_id}' not found")
                self.app_settings.flows[flow_id] = flow_file

            return datorum.PipeFlow.load(self.app_settings.flows[flow_id])


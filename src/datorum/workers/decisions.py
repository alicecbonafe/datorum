import multiprocessing
from typing import Any, Literal

from pydantic import BaseModel
from RestrictedPython import compile_restricted_eval, compile_restricted_exec
from RestrictedPython import safe_globals
from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
from RestrictedPython.Guards import (
    safer_getattr,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
)

from ..exceptions import DecisionWorkerException
from ..pipeline import CodeType
from .base import Worker, Job, JobStatus


_MP_CONTEXT = multiprocessing.get_context("spawn")

_CODE_TIMEOUT: float = 5.0
_CODE_MODES: dict[CodeType, str] = {
    CodeType.FORMULA: "eval",
    CodeType.SNIPPET: "exec",
}

_RESULT_VAR: str = "target"

def _restricted_globals() -> dict[str, Any]:
    g = dict(safe_globals)
    g["_getattr_"] = safer_getattr               # blocks `_private`/dunder access
    g["_getitem_"] = default_guarded_getitem      # input_data['field']
    g["_getiter_"] = default_guarded_getiter      # for/comprehension support
    g["_iter_unpack_sequence_"] = guarded_iter_unpack_sequence
    g["_unpack_sequence_"] = guarded_unpack_sequence
    return g

def _run_code(
    code: str,
    mode: Literal["eval", "exec"],
    input_data: dict,
    out_queue: "multiprocessing.Queue",
) -> None:
    try:
        glb = _restricted_globals()
        if mode == "eval":
            compiled = compile_restricted_eval(code, filename=f"<{_RESULT_VAR}>")
            if compiled.errors:
                raise SyntaxError("; ".join(compiled.errors))
            result = eval(compiled.code, glb, {"input_data": input_data})
        else:
            compiled = compile_restricted_exec(code, filename=f"<{_RESULT_VAR}>")
            if compiled.errors:
                raise SyntaxError("; ".join(compiled.errors))
            loc: dict[str, Any] = {"input_data": input_data}
            exec(compiled.code, glb, loc)
            if _RESULT_VAR not in loc:
                raise NameError(f"Snippet did not assign a value to '{_RESULT_VAR}'")
            result = loc[_RESULT_VAR]
        out_queue.put(("ok", result))
    except BaseException as exc:
        out_queue.put(("error", f"{type(exc).__name__}: {exc}"))

class DecisionWorker(Worker):
    required_documents: list[str] = ["input"]
    required_custom: list[str] = ["code", "code_type"]



    async def work(self, job: Job):
        await job.update_status(JobStatus.WORKING, "Collecting decision resources")

        code: str = job.context.custom["code"]
        code_type: CodeType = job.context.custom["code_type"]

        input_data = job.context.documents["input"].load()
        if isinstance(input_data, BaseModel):
            input_data = input_data.model_dump(mode="json")
        
        if not isinstance(input_data, dict):
            raise DecisionWorkerException(f"Invalid data input type: '{type(input_data)}'")

        await job.update_status(JobStatus.WORKING, "Running decision code")
        out_queue: "multiprocessing.Queue" = _MP_CONTEXT.Queue()
        process = _MP_CONTEXT.Process(
            target=self._run_code,
            args=(code, _CODE_MODES[code_type], input_data, out_queue),
            daemon=True,
        )
        process.start()
        process.join(_CODE_TIMEOUT)

        await job.update_status(JobStatus.WORKING, "Validating results")
        if process.is_alive():
            process.terminate()
            process.join()
            raise DecisionWorkerException(f"Timed out after {_CODE_TIMEOUT}s")

        if out_queue.empty():
            raise DecisionWorkerException(f"Process exited without a result (exit code {process.exitcode})",)

        status, result = out_queue.get()
        if status != "ok":
            raise DecisionWorkerException(f"Process error reported: {result}")

        job.context.custom["target_id"] = result




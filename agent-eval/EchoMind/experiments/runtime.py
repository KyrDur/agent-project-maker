"""Run Phase 2 in a private worker. Credentials travel over stdin only."""
import asyncio
import json
import os
import sys
from pathlib import Path
from .canonical import encoded
from .snapshots import ROOT, control_snapshot, runtime_identity

class ProcessRuntime:
    async def execute(self,run,credentials,worker_environment):
        # No shell, no disk credential/config input, no online objects in child.
        environment = {"PATH":os.environ.get("PATH",""),"PYTHONPATH":str(ROOT),
                       "PYTHONIOENCODING":"utf-8", **worker_environment}
        process = await asyncio.create_subprocess_exec(sys.executable,"-m","experiments.worker",
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
            env=environment,cwd=ROOT)
        payload = {"run":run.model_dump(mode="json"),"credential":credentials}
        try:
            stdout,_ = await asyncio.wait_for(process.communicate(encoded(payload)),timeout=1800)
        except (asyncio.TimeoutError,asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError("Experiment worker failed")
        output = json.loads(stdout)
        if output.get("error"):
            from .providers import ProviderFailure,FAILURE_CODES
            if output['error'] in FAILURE_CODES:
                raise ProviderFailure(output['error'])
            raise RuntimeError("Experiment worker failed")
        return output

"""Fresh recovery workers run under the declared fixture principal."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest


@pytest.mark.parametrize("principal", ["application", "issuer"])
def test_worker_cli_refuses_parent_identity_before_reading_configuration(tmp_path, principal):
    assert os.geteuid() not in (31001, 31002)
    missing = tmp_path / "CANARY_UNREAD_PRIVATE_CONFIGURATION.json"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.fixtures.r2.opportunity.manual_recovery_worker",
            "--principal",
            principal,
            "--config",
            str(missing),
            "--run-id",
            uuid4().hex,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert process.returncode == 2
    result = json.loads(process.stdout)
    assert result["error"] == "M9_WORKER_PRINCIPAL_MISMATCH"
    assert result["uid"] == os.geteuid()
    assert result["pid"] != os.getpid()
    assert "CANARY_UNREAD_PRIVATE_CONFIGURATION" not in process.stdout + process.stderr
    assert not missing.exists()


async def test_fresh_uid_application_acquires_once_and_replays_without_ports(scoped_runtime):
    first = await scoped_runtime.application("acquire")
    assert first["uid"] == 31002
    assert first["result"]["state"] == "SUCCEEDED"
    before = await scoped_runtime.application_journal()
    replay = await scoped_runtime.application("acquire")
    assert replay["uid"] == 31002
    assert replay["pid"] != first["pid"]
    assert replay["result"] == first["result"]
    after = await scoped_runtime.application_journal()
    assert sum(item["event"] == "fetch" for item in after) == 1
    assert sum(item["event"] == "admit" for item in after) == 1
    assert sum(item["event"] == "read" for item in after) == sum(item["event"] == "read" for item in before)
    assert sum(item["event"] == "private-authority-denied" for item in after) == 2
    assert scoped_runtime.parent_calls == []


@pytest.fixture(scope="session")
def recovery_runtime_export(tmp_path_factory):
    import hashlib
    import shutil
    import sysconfig
    from pathlib import Path

    repo = Path(__file__).resolve().parents[4]
    output = tmp_path_factory.mktemp("m9b-runtime-export")
    code = output / "code"
    code.mkdir()
    names = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode().split("\0"))
    names.update(
        (
            "tests/fixtures/r2/opportunity/manual_recovery_worker.py",
            "tests/fixtures/r2/opportunity/manual_recovery_restarts.json",
        )
    )
    hashes = {}
    for name in sorted(filter(None, names)):
        if not (
            (name.endswith(".py") and name.startswith(("lib/", "r2/", "server/", "scripts/", "tests/fixtures/")))
            or name
            in (
                "uv.lock",
                "pyproject.toml",
                "tests/fixtures/r2/opportunity/manual_import.json",
                "tests/fixtures/r2/opportunity/manual_recovery_restarts.json",
            )
        ):
            continue
        source = repo / name
        assert source.is_file()
        assert not source.is_symlink()
        target = code / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    bootstrap = r"""
import json,sys,sysconfig
from pathlib import Path
import asyncpg
from tests.fixtures.r2.opportunity.manual_recovery_worker import ApplicationConfig,IssuerConfig
from tests.fixtures.r2.opportunity.manual_admission_custodian import FixtureManualUploadCustodian
from server.services.opportunity_acquisition_v2 import HostManualAdmissionUnitOfWork
site=Path(sysconfig.get_paths()['purelib']);roots=set()
for module in list(sys.modules.values()):
 value=getattr(module,'__file__',None)
 if not isinstance(value,str):continue
 try:relative=Path(value).relative_to(site)
 except ValueError:continue
 roots.add(relative.parts[0])
print(json.dumps(sorted(roots)))
"""
    roots = json.loads(
        subprocess.check_output(
            [sys.executable, "-c", bootstrap],
            cwd=repo,
            text=True,
            env={**os.environ, "PYTHONPATH": str(repo), "ARCREEL_DATA_DIR": str(output / "bootstrap-data")},
            timeout=40,
        )
    )
    installed = __import__("pathlib").Path(sysconfig.get_paths()["purelib"])
    site = output / "site"
    site.mkdir()
    for name in roots:
        source = installed / name
        if source.is_dir():
            shutil.copytree(source, site / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copyfile(source, site / name)
    metadata = output / "metadata"
    metadata.mkdir()
    for pattern in ("cryptography-*.dist-info", "pydantic-*.dist-info", "pydantic_core-*.dist-info"):
        matches = list(installed.glob(pattern))
        assert len(matches) == 1
        shutil.copytree(matches[0], metadata / matches[0].name)
    for parent in (code, site, metadata):
        for entry in (parent, *parent.rglob("*")):
            entry.chmod(0o755 if entry.is_dir() else 0o644)
    hashes["tests/integration/r2/opportunity/test_acquisition_v2_restarts.py"] = hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest()
    return {
        "repo": repo,
        "code": code,
        "site": site,
        "metadata": metadata,
        "python": __import__("pathlib").Path(sys._base_executable).resolve().parents[1],
        "hashes": hashes,
    }


class RecoveryRuntime:
    image = "sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280"
    postgres = "9cf1d8726ff1198a2749985ccde704c2774e380f7649fb0a741ab1e501c04b03"

    def __init__(self, factory, scratch, export):
        import asyncio

        self.factory, self.scratch, self.export = factory, scratch.absolute(), export
        self.owner = uuid4().hex
        self.container = None
        self.server = None
        self.handlers = set()
        self.children = []
        self.issuer_results = []
        self.broker_errors = []
        self.original_request = None
        self.parent_calls = []
        self.selected_case = None
        self.closing = False
        self.child_started = asyncio.Condition()

    async def docker(self, *argv, body=None, allowed=(0,)):
        import asyncio

        process = await asyncio.create_subprocess_exec(
            "docker",
            *map(str, argv),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(40):
                stdout, stderr = await process.communicate(None if body is None else json.dumps(body).encode())
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        assert process.returncode in allowed, (process.returncode, stderr.decode())
        return process.returncode, stdout

    async def root(self, code, body=None):
        assert self.container is not None
        _, output = await self.docker(
            "exec", "-i", "--user", "0:0", self.container, "/opt/python/bin/python3.13", "-c", code, body=body
        )
        return json.loads(output)

    async def start(self):
        from sqlalchemy.engine import make_url

        if self.scratch.is_relative_to(self.export["repo"]):
            raise ValueError("recovery scratch must be outside the readonly source mount")
        if len(os.fsencode(self.scratch / "broker.sock")) >= 108:
            raise ValueError("recovery scratch exceeds the native Unix socket address limit")
        database_url = os.environ["DATABASE_URL"]
        target = make_url(database_url)
        assert (target.drivername, target.host, target.port, target.database, target.username) == (
            "postgresql+asyncpg",
            "127.0.0.1",
            32768,
            "m9b",
            "m9test",
        )
        _, raw = await self.docker("inspect", self.postgres)
        postgres = json.loads(raw)[0]
        assert postgres["State"]["Running"]
        assert postgres["Config"]["Labels"]["arcreel.disposable"] == "true"
        assert postgres["Config"]["Labels"]["arcreel.scope"] == "m9b-disposable-test"
        repo = self.export["repo"]
        _, result = await self.docker(
            "run",
            "--rm",
            "-d",
            "--pull=never",
            "--name",
            "m9b-recovery-" + self.owner,
            "--label",
            "arcreel.disposable=true",
            "--label",
            "arcreel.scope=m9b-recovery-runtime",
            "--label",
            "arcreel.owner=" + self.owner,
            "--network",
            "host",
            "--pid",
            "host",
            "--security-opt",
            "no-new-privileges:true",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "DATABASE_URL=" + database_url,
            "--env",
            "PYTHONPATH=" + str(repo) + ":/opt/site-packages:/opt/package-metadata",
            "--mount",
            "type=bind,src=" + str(self.export["code"]) + ",dst=" + str(repo) + ",readonly",
            "--mount",
            "type=bind,src=" + str(self.export["site"]) + ",dst=/opt/site-packages,readonly",
            "--mount",
            "type=bind,src=" + str(self.export["metadata"]) + ",dst=/opt/package-metadata,readonly",
            "--mount",
            "type=bind,src=" + str(self.export["python"]) + ",dst=/opt/python,readonly",
            "--mount",
            "type=bind,src=" + str(self.scratch) + ",dst=" + str(self.scratch),
            "--entrypoint",
            "/opt/python/bin/python3.13",
            self.image,
            "-c",
            "import time;time.sleep(3600)",
        )
        self.container = result.decode().strip()
        _, raw = await self.docker("inspect", self.container)
        info = json.loads(raw)[0]
        assert info["Id"] == self.container
        assert info["Config"]["Labels"]["arcreel.owner"] == self.owner
        assert info["Config"]["Labels"]["arcreel.scope"] == "m9b-recovery-runtime"
        self.init_pid = info["State"]["Pid"]

    async def configure(self, service, command, parent_calls, publication):
        import asyncio
        import hashlib

        from sqlalchemy import text

        from tests.fixtures.r2.opportunity.manual_recovery_worker import ApplicationConfig

        self.service, self.command, self.parent_calls, self.publication = service, command, parent_calls, publication
        assert service.descriptor is not None
        assert service.upload is not None
        async with service.store.transaction() as tx:
            query = await tx.queries.get_exact(command.query_id, command.query_revision)
            assert query is not None
            grant = await tx.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
            evaluation = await tx.capabilities.get_evaluation(query.capability_evaluation_id)
            schema = await tx.session.scalar(text("SELECT current_schema()"))
        assert grant is not None
        assert evaluation is not None
        source_fixture = self.export["repo"] / "tests/fixtures/r2/opportunity/manual_import.json"
        self.application_config = ApplicationConfig(
            run_id=uuid4().hex,
            case_id="combined-runtime-smoke",
            scratch_root=self.scratch,
            publication_root=publication.root,
            marker_root=self.scratch / "application-markers",
            operation="acquire",
            database_url=os.environ["DATABASE_URL"],
            database_schema=schema,
            command=command,
            descriptor=service.descriptor,
            upload=service.upload,
            public_key=publication.verifier.public_key.hex(),
            grant=grant,
            evaluation=evaluation,
            broker_socket=self.scratch / "broker.sock",
            source_fixture=source_fixture,
            source_fixture_digest="sha256:" + hashlib.sha256(source_fixture.read_bytes()).hexdigest(),
        )
        await self.root(
            r"""
import json,os,stat,sys
from pathlib import Path
body=json.load(sys.stdin);root=Path(body['scratch']);root.chmod(0o755)
for name,uid in [('issuer',31001),('publication',31002),('application-markers',31002),('issuer-markers',31001)]:
 path=root/name;path.mkdir(mode=0o700,exist_ok=True)
 for entry in [path,*path.rglob('*')]:
  assert not entry.is_symlink() and (entry.is_file() or entry.is_dir())
  os.chown(entry,uid,uid);entry.chmod(0o700 if entry.is_dir() else 0o600)
configuration=root/'configuration';configuration.mkdir(mode=0o755);os.chown(configuration,0,0)
print(json.dumps({'configured':True}))
""",
            {"scratch": str(self.scratch)},
        )
        self.server = await asyncio.start_unix_server(
            self.handle, path=str(self.application_config.broker_socket), limit=16_777_217
        )
        self.application_config.broker_socket.chmod(0o666)

    async def public_owner(self, uid):
        return await self.root(
            r"""
import json,os,stat,sys
from pathlib import Path
body=json.load(sys.stdin);root=Path(body['scratch']);private=root/'issuer';public=root/'publication'
assert private.stat().st_uid==31001 and stat.S_IMODE(private.stat().st_mode)==0o700
inode=public.stat().st_ino
for entry in [public,*public.rglob('*')]:
 assert not entry.is_symlink() and (entry.is_file() or entry.is_dir())
 os.chown(entry,body['uid'],body['uid'])
assert public.stat().st_ino==inode
print(json.dumps({'same_inode':True,'inode':inode}))
""",
            {"scratch": str(self.scratch), "uid": uid},
        )

    async def spawn(self, config):
        import asyncio

        from tests.fixtures.r2.opportunity.manual_recovery_worker import ApplicationConfig

        uid = 31002 if config.principal == "application" else 31001
        data = config.model_dump(mode="json")
        if isinstance(config, ApplicationConfig):
            data["database_url"] = config.database_url.get_secret_value()
        target = config.scratch_root / "configuration" / (config.run_id + ".config.json")
        await self.root(
            r"""
import json,os,sys
body=json.load(sys.stdin);raw=json.dumps(body['config']).encode();fd=os.open(body['path'],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
os.chown(body['path'],0,0);os.chmod(body['path'],0o444);print(json.dumps({'written':True}))
""",
            {"path": str(target), "config": data, "uid": uid},
        )
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "--user",
            f"{uid}:{uid}",
            "--env",
            f"ARCREEL_DATA_DIR=/tmp/m9-worker-data-{uid}",
            self.container,
            "/opt/python/bin/python3.13",
            "-m",
            "tests.fixtures.r2.opportunity.manual_recovery_worker",
            "--principal",
            config.principal,
            "--config",
            str(target),
            "--run-id",
            config.run_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        child = {
            "process": process,
            "config": config,
            "configuration_path": target,
            "communication": asyncio.create_task(process.communicate()),
        }
        self.children.append(child)
        async with self.child_started:
            self.child_started.notify_all()
        return child

    async def selected_issuer_child(self):
        import asyncio

        assert self.selected_case is not None
        async with asyncio.timeout(25), self.child_started:
            await self.child_started.wait_for(
                lambda: any(
                    child["config"].principal == "issuer" and child["config"].boundary == self.selected_case["boundary"]
                    for child in self.children
                )
            )
        return next(
            child
            for child in self.children
            if child["config"].principal == "issuer" and child["config"].boundary == self.selected_case["boundary"]
        )

    async def complete(self, child):
        import asyncio

        async with asyncio.timeout(35):
            stdout, stderr = await asyncio.shield(child["communication"])
        if child["process"].returncode == 137:
            return {
                "uid": 31002 if child["config"].principal == "application" else 31001,
                "pid": child.get("marker", {}).get("pid"),
                "error": "M9_REQUIRED_EVIDENCE_MISSING",
            }
        assert child["process"].returncode in (0, 2), (child["process"].returncode, stderr.decode())
        value = json.loads(stdout)
        assert value["uid"] == (31002 if child["config"].principal == "application" else 31001)
        child["value"] = value
        return value

    async def application(self, operation, *, boundary=None, stop_after=None, **updates):
        config = self.application_config.model_copy(
            update={
                "run_id": uuid4().hex,
                "operation": operation,
                "boundary": boundary,
                "stop_after": stop_after,
                **updates,
            }
        )
        child = await self.spawn(config)
        result = await self.complete(child)
        assert "error" not in result, f"module={result.get('missing_module')}; result={result}"
        return result

    async def handle(self, reader, writer):
        import asyncio
        import socket
        import struct

        from r2.opportunity.acquisition_v2_digests import digest_acquisition_request_v2
        from r2.opportunity.manual_admission import AdmissionRequest
        from tests.fixtures.r2.opportunity.manual_recovery_worker import IssuerConfig

        task = asyncio.current_task()
        self.handlers.add(task)
        operation = None
        try:
            _, uid, _ = struct.unpack(
                "3i", writer.get_extra_info("socket").getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            assert uid == 31002
            body = json.loads(await reader.readline())
            assert set(body) in ({"operation", "request"}, {"operation", "request", "claim_ref", "closure_id"})
            operation = body["operation"]
            assert operation in ("admit", "close")
            request = AdmissionRequest.model_validate(body["request"])
            original = self.application_config
            assert request.context == self.command.context
            assert request.request_digest == digest_acquisition_request_v2(self.command)
            assert request.descriptor == original.descriptor
            assert (request.opaque_upload_id, request.upload_version, request.data_rules, request.original_clocks) == (
                original.upload.opaque_upload_id,
                original.upload.upload_version,
                original.upload.data_rules,
                original.upload.original_clocks,
            )
            assert self.original_request is None or self.original_request == request
            self.original_request = request
            async with self.service.store.transaction() as tx:
                if operation == "admit":
                    envelope = await tx.manual.get_envelope(request.attempt_id)
                    assert envelope.phase == "RESERVED"
                    assert envelope.request == request
                else:
                    state = await tx.manual.get_cleanup_state(request.attempt_id)
                    assert (state.intent.phase, state.intent.version) == ("CLEANUP_PENDING", 2)
                    assert state.root_request == request
                    assert state.claim_ref == body["claim_ref"]
                    assert state.intent.closure_id == body["closure_id"]
            config = IssuerConfig(
                run_id=uuid4().hex,
                case_id=self.selected_case["case_id"] if self.selected_case else original.case_id,
                operation=operation,
                scratch_root=self.scratch,
                publication_root=original.publication_root,
                marker_root=self.scratch / "issuer-markers",
                private_root=self.scratch / "issuer",
                request=request,
                claim_ref=body.get("claim_ref"),
                closure_id=body.get("closure_id"),
                boundary=self.selected_case["boundary"]
                if self.selected_case and self.selected_case["principal"] == "issuer"
                else None,
            )
            if operation == "admit":
                await self.public_owner(31001)
            try:
                child = await self.spawn(config)
                result = await self.complete(child)
            finally:
                if operation == "admit" and not self.closing:
                    await self.public_owner(31002)
            if "error" in result:
                response = {"error": result["error"]}
            else:
                self.issuer_results.append(result)
                response = result["result"]
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
        except Exception as error:
            self.broker_errors.append(type(error).__name__ + ": " + str(error))
            writer.write(b'{"error":"M9_REQUIRED_EVIDENCE_MISSING"}\n')
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            self.handlers.discard(task)

    async def application_journal(self):
        return await self.root(
            r"""
import json,sys
from pathlib import Path
root=Path(json.load(sys.stdin)['scratch'])/'application-markers';records=[]
for path in root.glob('*.journal.jsonl'):
 records.extend(json.loads(line) for line in path.read_text().splitlines())
print(json.dumps(records))
""",
            {"scratch": str(self.scratch)},
        )

    async def kill(self, child):
        import asyncio
        import hashlib

        from scripts.r2.verify_m9_design_acceptance import loads_unique_json

        config = child["config"]
        uid = 31002 if config.principal == "application" else 31001
        pair = None
        async with asyncio.timeout(25):
            while pair is None:
                pair = await self.root(
                    r"""
import json,os,stat,sys
from pathlib import Path
body=json.load(sys.stdin);root=Path(body['root']);armed=root/(body['run_id']+'.armed.json')
if not armed.exists():print('null')
else:
 result={}
 for kind in ('arrival','armed'):
  path=root/(body['run_id']+'.'+kind+'.json');fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  with os.fdopen(fd,'rb') as stream:
   info=os.fstat(stream.fileno());assert stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==body['uid']
   raw=stream.read(8193);assert 0<len(raw)<=8192;result[kind]=raw.hex()
 print(json.dumps(result))
""",
                    {"root": str(config.marker_root), "run_id": config.run_id, "uid": uid},
                )
                if pair is None and child["process"].returncode is not None:
                    result = await self.complete(child)
                    pytest.fail("worker exited before the selected armed boundary: " + json.dumps(result))
                if pair is None:
                    await asyncio.sleep(0.01)
        raw = bytes.fromhex(pair["arrival"])
        armed_raw = bytes.fromhex(pair["armed"])
        marker, armed = loads_unique_json(raw), loads_unique_json(armed_raw)
        assert marker == {
            "schema": "m9-manual-recovery-arrival.v1",
            "case_id": config.case_id,
            "boundary": config.boundary,
            "pid": marker["pid"],
            "uid": uid,
        }
        assert armed == {
            "schema": "m9-manual-recovery-armed.v1",
            "case_id": config.case_id,
            "arrival_sha256": hashlib.sha256(raw).hexdigest(),
            "pid": marker["pid"],
        }
        child["marker"] = marker
        kernel = await self.root(
            r"""
import hashlib,json,os,signal,sys
body=json.load(sys.stdin);pid=body['pid'];assert pid>1 and pid!=os.getpid() and pid!=body['init_pid']
fd=os.pidfd_open(pid,0)
try:
 raw=open(f'/proc/{pid}/cmdline','rb').read();argv=raw.split(b'\0');token=body['run_id'].encode()
 assert b'tests.fixtures.r2.opportunity.manual_recovery_worker' in argv
 assert argv[argv.index(b'--run-id')+1]==token
 assert argv[argv.index(b'--principal')+1]==body['principal'].encode()
 status=open(f'/proc/{pid}/status').read();uids=next(x for x in status.splitlines() if x.startswith('Uid:')).split()[1:]
 assert set(uids)=={str(body['uid'])}
 signal.pidfd_send_signal(fd,signal.SIGKILL)
finally:os.close(fd)
print(json.dumps({'pid':pid,'uid':body['uid'],'pidfd_pinned':True,'parent_sent_sigkill':True,'argv_sha256':hashlib.sha256(raw).hexdigest()}))
""",
            {
                "pid": marker["pid"],
                "uid": uid,
                "run_id": config.run_id,
                "principal": config.principal,
                "init_pid": self.init_pid,
            },
        )
        async with asyncio.timeout(15):
            await asyncio.shield(child["communication"])
        assert child["process"].returncode == 137
        absent = await self.root(
            r"""
import json,sys
from pathlib import Path
body=json.load(sys.stdin);print(json.dumps({'old_pid_absent':not Path('/proc/'+str(body['pid'])).exists()}))
""",
            {"pid": marker["pid"]},
        )
        assert absent["old_pid_absent"]
        result = {
            "pid": marker["pid"],
            "uid": uid,
            "arrival_raw": raw,
            "armed_raw": armed_raw,
            "kernel": kernel,
            "reaped": True,
            "wait_exit_code": 137,
        }
        child["kill"] = result
        return result

    def persist_restart(self, case, killed, restarted):
        import hashlib
        import stat
        from pathlib import Path

        from lib.json_io import atomic_write_bytes
        from r2.advanced_creative.digests import canonical_json_bytes
        from scripts.r2.verify_m9_design_acceptance import loads_unique_json

        configured = os.environ.get("ARCREEL_M9_RECOVERY_ARTIFACT_DIR")
        root = Path(configured) if configured else self.export["code"].parent / "evidence"
        root = root.absolute()
        assert not any(path.is_symlink() for path in (root, *root.parents))
        assert not root.is_relative_to(self.scratch)
        if configured:
            info = root.stat()
            assert info.st_uid == os.geteuid()
            assert stat.S_IMODE(info.st_mode) == 0o700
            owner = loads_unique_json((root / ".m9b-recovery-owner.json").read_bytes())
            assert owner["repo"] == str(self.export["repo"])
        else:
            root.mkdir(mode=0o700, exist_ok=True)
        target = root / "restarts"
        target.mkdir(mode=0o700, exist_ok=True)
        assert not target.is_symlink()
        assert target.stat().st_uid == os.geteuid()
        identity = case["case_id"]
        assert identity.replace("-", "").isalnum()
        uid = 31001 if case["principal"] == "issuer" else 31002
        marker = loads_unique_json(killed["arrival_raw"])
        assert (marker["case_id"], marker["boundary"], marker["uid"], marker["pid"]) == (
            identity,
            case["boundary"],
            uid,
            killed["pid"],
        )
        assert killed["reaped"] is True
        assert killed["wait_exit_code"] == 137
        assert killed["kernel"]["pidfd_pinned"] is True
        assert killed["kernel"]["parent_sent_sigkill"] is True
        assert restarted["uid"] == uid
        assert len({os.getpid(), killed["pid"], restarted["pid"]}) == 3
        record = {
            "schema": "m9-manual-recovery-restart.v1",
            "case_id": identity,
            "worker_uid": uid,
            "parent_pid": os.getpid(),
            "killed_pid": killed["pid"],
            "restarted_pid": restarted["pid"],
            "passed": True,
            "parent_killed": True,
            "reaped": True,
            "marker_fsynced": True,
            "marker_sha256": hashlib.sha256(killed["arrival_raw"]).hexdigest(),
            "armed_sha256": hashlib.sha256(killed["armed_raw"]).hexdigest(),
            "kernel": killed["kernel"],
            "wait_exit_code": killed["wait_exit_code"],
            "source_hashes": self.export["hashes"],
        }
        for suffix, raw in (
            ("arrival.json", killed["arrival_raw"]),
            ("armed.json", killed["armed_raw"]),
            ("json", canonical_json_bytes(record)),
        ):
            path = target / (identity + "." + suffix)
            assert not path.exists()
            assert not path.is_symlink()
            atomic_write_bytes(path, raw)
        for directory in (target, root):
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    async def close(self):
        import asyncio

        self.closing = True
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        if self.container is None:
            return
        _, raw = await self.docker("inspect", self.container)
        info = json.loads(raw)[0]
        assert info["Id"] == self.container
        assert info["Config"]["Labels"]["arcreel.owner"] == self.owner
        assert info["Config"]["Labels"]["arcreel.scope"] == "m9b-recovery-runtime"
        for task in tuple(self.handlers):
            task.cancel()
        if self.handlers:
            await asyncio.gather(*tuple(self.handlers), return_exceptions=True)
        await self.docker("stop", "--time", "1", self.container)
        for child in self.children:
            if not child["communication"].done():
                async with asyncio.timeout(15):
                    await asyncio.shield(child["communication"])
        restore = r"""
import json,os,sys
body=json.load(sys.stdin)
for current,dirs,files in os.walk('/owned',followlinks=False):
 for name in dirs+files:os.lchown(os.path.join(current,name),body['uid'],body['gid'])
os.chown('/owned',body['uid'],body['gid']);print(json.dumps({'owned_reaped_scratch_restored':True}))
"""
        await self.docker(
            "run",
            "--rm",
            "-i",
            "--pull=never",
            "--network",
            "none",
            "--label",
            "arcreel.disposable=true",
            "--label",
            "arcreel.scope=m9b-recovery-cleanup",
            "--label",
            "arcreel.owner=" + self.owner,
            "--mount",
            "type=bind,src=" + str(self.scratch) + ",dst=/owned",
            "--mount",
            "type=bind,src=" + str(self.export["python"]) + ",dst=/opt/python,readonly",
            "--entrypoint",
            "/opt/python/bin/python3.13",
            self.image,
            "-c",
            restore,
            body={"uid": os.geteuid(), "gid": os.getegid()},
        )


@pytest.fixture
async def scoped_runtime(session_factory, tmp_path, recovery_runtime_export):
    from tests.integration.r2.opportunity.test_acquisition_v2 import service_subject

    runtime = RecoveryRuntime(session_factory, tmp_path, recovery_runtime_export)
    await runtime.start()
    try:
        service, command, calls, publication = await service_subject(session_factory, tmp_path, cleanup=True)
        await runtime.configure(service, command, calls, publication)
        yield runtime
    finally:
        await runtime.close()


@pytest.fixture(scope="session")
def restart_inventory():
    from pathlib import Path

    from scripts.r2.verify_m9_design_acceptance import loads_unique_json

    return loads_unique_json(
        (
            Path(__file__).resolve().parents[4] / "tests/fixtures/r2/opportunity/manual_recovery_restarts.json"
        ).read_bytes()
    )


@pytest.mark.parametrize(
    "stage",
    [
        "ready-committed",
        "claim-before-commit",
        "claim-committed",
        "before-source-dispatch",
        "source-response-returned",
        "checkpoint-before-commit",
        "checkpoint-committed",
        "finalization-before-commit",
    ],
)
async def test_parent_kill_after_claim_reconstructs_original_material_without_repeating_fetch(
    scoped_runtime, restart_inventory, stage
):
    inventory = restart_inventory
    case = next(c for c in inventory["cases"] if c["case_id"] == "application-acquire-" + stage)
    scoped_runtime.selected_case = case
    config = scoped_runtime.application_config.model_copy(
        update={
            "case_id": case["case_id"],
            "run_id": uuid4().hex,
            "boundary": case["boundary"],
        }
    )
    child = await scoped_runtime.spawn(config)
    killed = await scoped_runtime.kill(child)
    async with scoped_runtime.service.store.transaction() as tx:
        original_attempt = await tx.manual.get_for_command(scoped_runtime.command)
        original_envelope = await tx.manual.get_envelope(original_attempt.attempt_id)
        assert original_attempt.state == "RUNNING"
        assert (original_envelope.dispatch_claim is None) == (stage in ("ready-committed", "claim-before-commit"))
    recovered = await scoped_runtime.application("reconstruct", case_id=case["case_id"])
    assert recovered["pid"] != killed["pid"]
    assert recovered["result"]["state"] == "OUTCOME_UNKNOWN"
    assert len(recovered["result"]["snapshot_ids"]) == 1
    async with scoped_runtime.service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(original_attempt.attempt_id)
        snapshot, provenance = await tx.manual.get_snapshot_for_attempt(original_attempt.attempt_id)
        if stage in ("ready-committed", "claim-before-commit"):
            assert envelope.request == original_envelope.request
            assert envelope.objects == original_envelope.objects
            assert envelope.admitted_at == original_envelope.admitted_at
            assert envelope.deadlines == original_envelope.deadlines
            assert envelope.dispatch_claim is not None
        else:
            assert envelope == original_envelope
        assert provenance.origin == "LOCAL_ADMISSION_RECONSTRUCTION"
        assert snapshot.provider_observed_at is None
    events = await scoped_runtime.application_journal()
    assert sum(item["event"] == "fetch" for item in events) == (
        1
        if stage
        in (
            "source-response-returned",
            "checkpoint-before-commit",
            "checkpoint-committed",
            "finalization-before-commit",
        )
        else 0
    )
    assert sum(item["event"] == "admit" for item in events) == 1
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, recovered)


@pytest.mark.parametrize("stage", ["reconstruction-fenced", "reconstruction-checkpoint-committed"])
async def test_parent_kill_reconstruction_keeps_original_anchor_and_unknown_delivery(
    scoped_runtime, restart_inventory, stage
):
    initial = await scoped_runtime.application("acquire", stop_after="claim-committed")
    assert initial["result"]["state"] == "RUNNING"
    case = next(c for c in restart_inventory["cases"] if c["operation"] == "reconstruct" and c["boundary"] == stage)
    config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"], "run_id": uuid4().hex, "operation": "reconstruct", "boundary": stage}
    )
    async with scoped_runtime.service.store.transaction() as tx:
        original = await tx.manual.get_envelope(initial["result"]["attempt_id"])
    killed = await scoped_runtime.kill(await scoped_runtime.spawn(config))
    recovered = await scoped_runtime.application("reconstruct", case_id=case["case_id"])
    assert recovered["result"]["state"] == "OUTCOME_UNKNOWN"
    assert len(recovered["result"]["snapshot_ids"]) == 1
    async with scoped_runtime.service.store.transaction() as tx:
        assert await tx.manual.get_envelope(initial["result"]["attempt_id"]) == original
        snapshot, provenance = await tx.manual.get_snapshot_for_attempt(initial["result"]["attempt_id"])
        assert snapshot.provider_observed_at is None
        assert provenance.origin == "LOCAL_ADMISSION_RECONSTRUCTION"
    assert not any(e["event"] == "fetch" for e in await scoped_runtime.application_journal())
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, recovered)


@pytest.mark.parametrize(
    "stage",
    [
        "issuer-header-seal-durable",
        "custodian-original-header-durable",
        "publication-header-durable",
        "publication-payloads-durable",
        "publication-integrities-durable",
        "publication-attestations-durable",
        "publication-complete",
        "issuer-material:raw-page-seal-durable",
        "issuer-material:source-identity-1-seal-durable",
        "issuer-material:source-identity-2-seal-durable",
        "issuer-material:native-field-1-seal-durable",
        "issuer-material:native-field-2-seal-durable",
        "issuer-material:manual-native-index-seal-durable",
    ],
)
async def test_parent_kill_issuer_admission_resumes_original_publication(scoped_runtime, restart_inventory, stage):
    case = next(c for c in restart_inventory["cases"] if c["operation"] == "admit" and c["boundary"] == stage)
    scoped_runtime.selected_case = case
    scoped_runtime.application_config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"]}
    )
    config = scoped_runtime.application_config.model_copy(update={"run_id": uuid4().hex})
    application = await scoped_runtime.spawn(config)
    issuer = await scoped_runtime.selected_issuer_child()
    killed = await scoped_runtime.kill(issuer)
    interrupted = await scoped_runtime.complete(application)
    assert interrupted["error"] == "M9_REQUIRED_EVIDENCE_MISSING"
    async with scoped_runtime.service.store.transaction() as tx:
        retained = await tx.manual.get_current_receipt(scoped_runtime.command)
        assert retained.state == "RUNNING"
        reserved = await tx.manual.get_envelope(retained.attempt_id)
        assert reserved.phase == "RESERVED"
        assert reserved.admitted_at is None
    scoped_runtime.selected_case = None
    await scoped_runtime.application("publication", case_id=case["case_id"])
    restarted = scoped_runtime.issuer_results[-1]
    assert restarted["uid"] == 31001
    assert restarted["pid"] != killed["pid"]
    async with scoped_runtime.service.store.transaction() as tx:
        ready = await tx.manual.get_envelope(retained.attempt_id)
        assert ready.phase == "READY"
        assert ready.request == reserved.request
        assert ready.dispatch_claim is None
        clocks = {clock.data_class: clock for clock in reserved.request.original_clocks}
        assert all(obj.original_clocks == tuple(clocks[name] for name in obj.data_classes) for obj in ready.objects)
    recovered = await scoped_runtime.application("reconstruct", case_id=case["case_id"])
    assert recovered["result"]["state"] == "OUTCOME_UNKNOWN"
    assert len(recovered["result"]["snapshot_ids"]) == 1
    async with scoped_runtime.service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(retained.attempt_id)
        assert envelope.admitted_at == ready.admitted_at
        assert envelope.deadlines == ready.deadlines
        assert envelope.objects == ready.objects
    assert not any(e["event"] == "fetch" for e in await scoped_runtime.application_journal())
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, restarted)


async def test_store_writer_uid_cannot_replace_original_binding_configuration(scoped_runtime):
    await scoped_runtime.application("acquire")
    child = next(c for c in scoped_runtime.children if c["config"].principal == "application")
    _, raw = await scoped_runtime.docker(
        "exec",
        "-i",
        "--user",
        "31002:31002",
        scoped_runtime.container,
        "/opt/python/bin/python3.13",
        "-c",
        r"""
import json,os,sys
from pathlib import Path
body=json.load(sys.stdin);path=Path(body['config']);denied=[]
try:fd=os.open(path,os.O_WRONLY|os.O_NOFOLLOW)
except PermissionError:denied.append('write-binding')
else:os.close(fd)
probe=path.parent/'untrusted-binding-probe'
try:fd=os.open(probe,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
except PermissionError:denied.append('replace-binding')
else:os.close(fd);probe.unlink()
print(json.dumps({'uid':os.geteuid(),'denied':denied}))
""",
        body={"config": str(child["configuration_path"])},
    )
    assert json.loads(raw) == {"uid": 31002, "denied": ["write-binding", "replace-binding"]}


@pytest.mark.parametrize(
    "stage",
    [
        "planned-committed",
        "reserved-committed",
        "publication-returned",
        "ready-before-commit",
        "finalization-committed",
    ],
)
async def test_parent_kill_preserves_initial_admission_and_exact_terminal_replay(
    scoped_runtime, restart_inventory, stage
):
    case = next(c for c in restart_inventory["cases"] if c["case_id"] == "application-acquire-" + stage)
    scoped_runtime.selected_case = case
    config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"], "run_id": uuid4().hex, "boundary": stage}
    )
    killed = await scoped_runtime.kill(await scoped_runtime.spawn(config))
    async with scoped_runtime.service.store.transaction() as tx:
        retained = await tx.manual.get_current_receipt(scoped_runtime.command)
        original = await tx.manual.get_envelope(retained.attempt_id)
    events = await scoped_runtime.application_journal()
    replay = await scoped_runtime.application("acquire", case_id=case["case_id"])
    assert replay["result"] == retained.model_dump(mode="json")
    after = await scoped_runtime.application_journal()
    assert [e for e in after if e["event"] != "private-authority-denied"] == [
        e for e in events if e["event"] != "private-authority-denied"
    ]
    if stage == "planned-committed":
        assert retained.state == "PLANNED"
        assert original is None
        assert not any(e["event"] in ("admit", "fetch") for e in after)
    elif stage == "finalization-committed":
        assert retained.state == "SUCCEEDED"
        assert len(retained.snapshot_ids) == 1
        async with scoped_runtime.service.store.transaction() as tx:
            snapshot, provenance = await tx.manual.get_snapshot_for_attempt(retained.attempt_id)
            assert provenance.origin == "SOURCE_RESPONSE_VERIFIED"
            checkpoints = await tx.manual.list_checkpoints(retained.attempt_id)
            assert snapshot.provider_observed_at == checkpoints[0].provider_observed_at
            assert provenance.response_recorded_at is not None
            assert await tx.manual.get_envelope(retained.attempt_id) == original
    else:
        assert retained.state == "RUNNING"
        assert original.phase == "RESERVED"
        assert original.admitted_at is None
        assert original.objects == ()
        assert original.dispatch_claim is None
        assert not any(e["event"] == "fetch" for e in after)
        if stage == "reserved-committed":
            assert not any(e["event"] == "admit" for e in after)
        else:
            publication = scoped_runtime.issuer_results[0]["result"]["publication"]
            await scoped_runtime.application("publication", case_id=case["case_id"])
            async with scoped_runtime.service.store.transaction() as tx:
                ready = await tx.manual.get_envelope(retained.attempt_id)
                assert ready.phase == "READY"
                assert ready.request == original.request
                assert ready.claim_ref == publication["claim_ref"]
                assert [obj.model_dump(mode="json") for obj in ready.objects] == publication["objects"]
                assert ready.dispatch_claim is None
            recovered = await scoped_runtime.application("reconstruct", case_id=case["case_id"])
            assert recovered["result"]["state"] == "OUTCOME_UNKNOWN"
            assert len(recovered["result"]["snapshot_ids"]) == 1
            async with scoped_runtime.service.store.transaction() as tx:
                final = await tx.manual.get_envelope(retained.attempt_id)
                assert final.admitted_at == ready.admitted_at
                assert final.deadlines == ready.deadlines
                assert final.objects == ready.objects
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, replay)


@pytest.mark.parametrize(
    ("stage", "version", "private_erased", "public_erased"),
    [
        ("cleanup-fence-before-commit", None, False, False),
        ("cleanup-fenced-committed", 1, False, False),
        ("recovery-publication-fence-durable", 1, False, False),
        ("cleanup-publication-fenced", 1, False, False),
        ("cleanup-drain-before-commit", 1, False, False),
        ("cleanup-drained-committed", 2, False, False),
        ("cleanup-private-erasure-returned", 2, True, False),
        ("cleanup-authorization-before-commit", 2, True, False),
        ("cleanup-authorized-committed", 3, True, False),
        ("cleanup-public-erasure-returned", 3, True, True),
        ("cleanup-completion-before-commit", 3, True, True),
        ("cleanup-erased-committed", 4, True, True),
    ],
)
async def test_parent_kill_cleanup_reconciles_physical_deletion_with_sql_commit(
    scoped_runtime, restart_inventory, stage, version, private_erased, public_erased
):
    acquired = await scoped_runtime.application("acquire")
    case = next(c for c in restart_inventory["cases"] if c["case_id"] == "application-cleanup-" + stage)
    scoped_runtime.selected_case = case
    config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"], "run_id": uuid4().hex, "operation": "cleanup", "boundary": stage}
    )
    killed = await scoped_runtime.kill(await scoped_runtime.spawn(config))
    attempt_id = acquired["result"]["attempt_id"]
    async with scoped_runtime.service.store.transaction() as tx:
        pending = await tx.manual.get_cleanup_state(attempt_id)
        envelope = await tx.manual.get_envelope(attempt_id)
        assert (pending is None) == (version is None)
        if pending is not None:
            assert pending.intent.version == version
        assert envelope.phase == ("READY" if version is None else "ERASED" if version == 4 else "CLEANUP_PENDING")
    physical = await scoped_runtime.root(
        r"""
import json,sys
from pathlib import Path
root=Path(json.load(sys.stdin)['scratch'])
print(json.dumps({'private_erased':not (root/'issuer'/'original.json').exists(),'public_erased':not list((root/'publication').rglob('payloads/*'))}))
""",
        {"scratch": str(scoped_runtime.scratch)},
    )
    assert physical == {"private_erased": private_erased, "public_erased": public_erased}
    recovered = await scoped_runtime.application("cleanup", case_id=case["case_id"])
    assert (recovered["result"]["phase"], recovered["result"]["version"]) == ("ERASED", 4)
    async with scoped_runtime.service.store.transaction() as tx:
        completed = await tx.manual.get_cleanup_state(attempt_id)
        assert completed.intent.model_dump(mode="json") == recovered["result"]
        assert (await tx.manual.get_envelope(attempt_id)).phase == "ERASED"
    if pending is not None:
        assert completed.intent.closure_id == pending.intent.closure_id
        assert completed.intent.fenced_at == pending.intent.fenced_at
        if pending.proof is not None:
            assert completed.proof == pending.proof
    before = await scoped_runtime.application_journal()
    exact = await scoped_runtime.application("cleanup", case_id=case["case_id"])
    assert exact["result"] == recovered["result"]
    after = await scoped_runtime.application_journal()
    assert [e for e in before if e["event"] != "private-authority-denied"] == [
        e for e in after if e["event"] != "private-authority-denied"
    ]
    assert sum(e["event"] == "fetch" for e in after) == 1
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, recovered)


@pytest.mark.parametrize(
    "stage",
    [
        "custodian-spend-plan-durable",
        "custodian-spent-state-durable",
        "custodian-spent-fence-durable",
        "custodian-private-object-unlinked",
        "custodian-original-unlinked",
        "custodian-comparison-unlinked",
        "custodian-spend-receipt-durable",
        "custodian-header-unlinked",
        "custodian-material-seal-unlinked",
        "custodian-temporary-unlinked",
    ],
)
async def test_parent_kill_private_erasure_reuses_original_spend_proof(scoped_runtime, restart_inventory, stage):
    acquired = await scoped_runtime.application("acquire")
    case = next(c for c in restart_inventory["cases"] if c["operation"] == "close" and c["boundary"] == stage)
    scoped_runtime.selected_case = case
    scoped_runtime.application_config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"]}
    )
    if stage == "custodian-temporary-unlinked":
        await scoped_runtime.root(
            r"""
import json,os,sys
from pathlib import Path
root=Path(json.load(sys.stdin)['scratch'])/'issuer';path=root/'.rollback.m9b-owned.tmp'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'wb') as stream:stream.write(b'synthetic unfinished fixture material');stream.flush();os.fsync(stream.fileno())
os.chown(path,31001,31001);fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY);os.fsync(fd);os.close(fd)
print(json.dumps({'owned_temporary_seeded':True}))
""",
            {"scratch": str(scoped_runtime.scratch)},
        )
    config = scoped_runtime.application_config.model_copy(update={"run_id": uuid4().hex, "operation": "cleanup"})
    application = await scoped_runtime.spawn(config)
    issuer = await scoped_runtime.selected_issuer_child()
    killed = await scoped_runtime.kill(issuer)
    interrupted = await scoped_runtime.complete(application)
    assert interrupted["error"] == "M9_REQUIRED_EVIDENCE_MISSING"
    async with scoped_runtime.service.store.transaction() as tx:
        pending = await tx.manual.get_cleanup_state(acquired["result"]["attempt_id"])
        assert pending.intent.version == 2
        assert pending.proof is None
    scoped_runtime.selected_case = None
    recovered = await scoped_runtime.application("cleanup", case_id=case["case_id"])
    assert (recovered["result"]["phase"], recovered["result"]["version"]) == ("ERASED", 4)
    restarted = scoped_runtime.issuer_results[-1]
    assert restarted["uid"] == 31001
    assert restarted["pid"] != killed["pid"]
    async with scoped_runtime.service.store.transaction() as tx:
        completed = await tx.manual.get_cleanup_state(acquired["result"]["attempt_id"])
        assert completed.intent.closure_id == pending.intent.closure_id
        assert completed.intent.fenced_at == pending.intent.fenced_at
        assert completed.proof.model_dump(mode="json") == restarted["result"]["proof"]
    before = len(scoped_runtime.issuer_results)
    replay = await scoped_runtime.application("cleanup", case_id=case["case_id"])
    assert replay["result"] == recovered["result"]
    assert len(scoped_runtime.issuer_results) == before
    assert sum(e["event"] == "fetch" for e in await scoped_runtime.application_journal()) == 1
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, restarted)


@pytest.mark.parametrize(
    "stage",
    [
        "recovery-deletion-plan-durable",
        "recovery-deletion-fence-durable",
        "recovery-deletion-attestations-durable",
        "recovery-deletion-headers-durable",
        "recovery-deletion-integrities-durable",
        "recovery-deletion-payloads-durable",
        "recovery-deletion-receipt-durable",
    ],
)
async def test_parent_kill_public_erasure_reuses_exact_receipt_before_sql_completion(
    scoped_runtime, restart_inventory, stage
):
    acquired = await scoped_runtime.application("acquire")
    setup = await scoped_runtime.application("cleanup", stop_after="cleanup-authorized-committed")
    assert setup["result"]["version"] == 3
    async with scoped_runtime.service.store.transaction() as tx:
        pending = await tx.manual.get_cleanup_state(acquired["result"]["attempt_id"])
        assert pending.proof is not None
    case = next(c for c in restart_inventory["cases"] if c["operation"] == "delete" and c["boundary"] == stage)
    config = scoped_runtime.application_config.model_copy(
        update={
            "case_id": case["case_id"],
            "run_id": uuid4().hex,
            "operation": "delete",
            "boundary": stage,
            "closure": pending.intent,
            "spending_proof": pending.proof,
            "deletion_requests": pending.requests,
        }
    )
    killed = await scoped_runtime.kill(await scoped_runtime.spawn(config))
    recovered = await scoped_runtime.application(
        "delete",
        case_id=case["case_id"],
        closure=pending.intent,
        spending_proof=pending.proof,
        deletion_requests=pending.requests,
    )
    replay = await scoped_runtime.application(
        "delete",
        case_id=case["case_id"],
        closure=pending.intent,
        spending_proof=pending.proof,
        deletion_requests=pending.requests,
    )
    assert replay["result"] == recovered["result"]
    async with scoped_runtime.service.store.transaction() as tx:
        assert await tx.manual.get_cleanup_state(acquired["result"]["attempt_id"]) == pending
    completed = await scoped_runtime.application("cleanup", case_id=case["case_id"])
    assert (completed["result"]["phase"], completed["result"]["version"]) == ("ERASED", 4)
    assert completed["result"]["closure_id"] == pending.intent.closure_id
    assert sum(e["event"] == "fetch" for e in await scoped_runtime.application_journal()) == 1
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, recovered)


@pytest.mark.parametrize(
    ("stage", "recoverable"),
    [
        ("custodian-claim-custody-durable", False),
        ("custodian-comparison-durable", False),
        ("custodian-upload-index-durable", True),
        ("custodian-command-index-durable", True),
    ],
)
async def test_parent_kill_original_claim_index_never_allocates_a_replacement_claim(
    scoped_runtime, restart_inventory, stage, recoverable
):
    case = next(c for c in restart_inventory["cases"] if c["operation"] == "admit" and c["boundary"] == stage)
    scoped_runtime.selected_case = case
    scoped_runtime.application_config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"]}
    )
    initial = await scoped_runtime.spawn(scoped_runtime.application_config.model_copy(update={"run_id": uuid4().hex}))
    killed = await scoped_runtime.kill(await scoped_runtime.selected_issuer_child())
    assert (await scoped_runtime.complete(initial))["error"] == "M9_REQUIRED_EVIDENCE_MISSING"
    claim = await scoped_runtime.root(
        r"""
import json,sys
from pathlib import Path
root=Path(json.load(sys.stdin)['scratch'])/'issuer';body=json.loads((root/'custody.json').read_text())
print(json.dumps({'claim_ref':body['claim_ref']}))
""",
        {"scratch": str(scoped_runtime.scratch)},
    )
    assert claim["claim_ref"] is not None
    async with scoped_runtime.service.store.transaction() as tx:
        receipt = await tx.manual.get_current_receipt(scoped_runtime.command)
        original = await tx.manual.get_envelope(receipt.attempt_id)
        assert original.phase == "RESERVED"
        assert original.admitted_at is None
    scoped_runtime.selected_case = None
    config = scoped_runtime.application_config.model_copy(update={"run_id": uuid4().hex, "operation": "publication"})
    publication = await scoped_runtime.complete(await scoped_runtime.spawn(config))
    if recoverable:
        assert publication["result"]["state"] == "RUNNING"
        async with scoped_runtime.service.store.transaction() as tx:
            ready = await tx.manual.get_envelope(receipt.attempt_id)
            assert ready.phase == "READY"
            assert ready.claim_ref == claim["claim_ref"]
            assert ready.request == original.request
        recovered = await scoped_runtime.application("reconstruct", case_id=case["case_id"])
        assert recovered["result"]["state"] == "OUTCOME_UNKNOWN"
        assert len(recovered["result"]["snapshot_ids"]) == 1
    else:
        assert publication["error"] == "M9_RAW_DIGEST_MISMATCH"
        async with scoped_runtime.service.store.transaction() as tx:
            assert await tx.manual.get_envelope(receipt.attempt_id) == original
        completed = await scoped_runtime.application("cleanup", case_id=case["case_id"])
        assert (completed["result"]["phase"], completed["result"]["version"]) == ("ERASED", 4)
        async with scoped_runtime.service.store.transaction() as tx:
            state = await tx.manual.get_cleanup_state(receipt.attempt_id)
            erased = await tx.manual.get_envelope(receipt.attempt_id)
            assert erased.admitted_at is None
            assert erased.objects == ()
            assert state.proof.metadata.claim_ref == claim["claim_ref"]
            assert all(p.state == "NEVER_ISSUED" and p.header is None for p in state.proof.metadata.publications)
    restarted = scoped_runtime.issuer_results[-1]
    assert restarted["uid"] == 31001
    assert restarted["pid"] != killed["pid"]
    assert not any(e["event"] == "fetch" for e in await scoped_runtime.application_journal())
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, restarted)


async def test_store_writer_uid_payload_and_hash_rewrite_cannot_forge_original_authority(scoped_runtime):
    acquired = await scoped_runtime.application("acquire")
    publication = scoped_runtime.issuer_results[0]["result"]["publication"]
    raw_object = next(obj for obj in publication["objects"] if obj["evidence_kind"] == "raw-page")
    _, output = await scoped_runtime.docker(
        "exec",
        "-i",
        "--user",
        "31002:31002",
        scoped_runtime.container,
        "/opt/python/bin/python3.13",
        "-c",
        r"""
import hashlib,json,os,re,sys
from pathlib import Path
from r2.advanced_creative.digests import canonical_json_bytes
body=json.load(sys.stdin);obj=body['object'];scope=hashlib.sha256(canonical_json_bytes(body['scope'])).hexdigest()
root=Path(body['root'])/'manual-publications'/scope
def path(ref,kind,folder,suffix):
 match=re.fullmatch('m9-manual-'+kind+':([0-9a-f]{32})',ref);assert match is not None
 return root/folder/(match[1]+suffix)
raw=b'WRITER_FORGERY_CANARY';payload=path(obj['payload_ref'],'payload','payloads','.bin')
integrity=path(obj['integrity_ref'],'integrity','integrities','.json')
for target,data in [(payload,raw),(integrity,canonical_json_bytes({'payload_ref':obj['payload_ref'],'integrity_ref':obj['integrity_ref'],'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}))]:
 fd=os.open(target,os.O_WRONLY|os.O_TRUNC|os.O_NOFOLLOW)
 with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
print(json.dumps({'uid':os.geteuid(),'payload_and_ordinary_hash_rewritten':True}))
""",
        body={
            "root": str(scoped_runtime.application_config.publication_root),
            "object": raw_object,
            "scope": {
                "user_id": scoped_runtime.command.context.user_id,
                "project_name": scoped_runtime.command.context.project_name,
            },
        },
    )
    assert json.loads(output) == {"uid": 31002, "payload_and_ordinary_hash_rewritten": True}
    config = scoped_runtime.application_config.model_copy(update={"run_id": uuid4().hex, "operation": "inspect"})
    refused = await scoped_runtime.complete(await scoped_runtime.spawn(config))
    assert refused["error"] == "M9_RAW_DIGEST_MISMATCH"
    assert "WRITER_FORGERY_CANARY" not in json.dumps(refused)
    before = await scoped_runtime.application_journal()
    replay = await scoped_runtime.application("acquire")
    assert replay["result"] == acquired["result"]
    after = await scoped_runtime.application_journal()
    assert sum(e["event"] == "read" for e in before) == sum(e["event"] == "read" for e in after)
    erased = await scoped_runtime.application("cleanup")
    assert (erased["result"]["phase"], erased["result"]["version"]) == ("ERASED", 4)
    assert scoped_runtime.parent_calls == []


async def test_parent_kill_expiry_keeps_original_clock_and_terminal_unknown_delivery(scoped_runtime, restart_inventory):
    import asyncio

    acquired = await scoped_runtime.application("acquire", stop_after="claim-committed")
    async with scoped_runtime.service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(acquired["result"]["attempt_id"])
        deadline = envelope.deadlines.refresh_due_at
    assert deadline is not None
    async with asyncio.timeout(40):
        while True:
            async with scoped_runtime.service.store.transaction() as tx:
                now = await tx.profiles.database_time()
            if now >= deadline:
                break
            elapsed = asyncio.Event()
            timer = asyncio.get_running_loop().call_later((deadline - now).total_seconds(), elapsed.set)
            try:
                await elapsed.wait()
            finally:
                timer.cancel()
    case = next(c for c in restart_inventory["cases"] if c["operation"] == "expire")
    config = scoped_runtime.application_config.model_copy(
        update={"case_id": case["case_id"], "run_id": uuid4().hex, "operation": "expire", "boundary": case["boundary"]}
    )
    killed = await scoped_runtime.kill(await scoped_runtime.spawn(config))
    async with scoped_runtime.service.store.transaction() as tx:
        retained = await tx.manual.get_current_receipt(scoped_runtime.command)
        original = await tx.manual.get_envelope(retained.attempt_id)
        assert original.admitted_at == envelope.admitted_at
        assert original.deadlines == envelope.deadlines
        assert retained.state == "EXPIRED_UNRECOVERABLE"
        assert retained.outcome_reason == "RESPONSE_OUTCOME_UNKNOWN"
        assert retained.snapshot_ids == ()
    recovered = await scoped_runtime.application("acquire", case_id=case["case_id"])
    assert recovered["result"] == retained.model_dump(mode="json")
    assert not any(e["event"] == "fetch" for e in await scoped_runtime.application_journal())
    assert scoped_runtime.parent_calls == []
    scoped_runtime.persist_restart(case, killed, recovered)

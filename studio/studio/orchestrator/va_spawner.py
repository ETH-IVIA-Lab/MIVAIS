"""Spawn and supervise VA subprocesses, one per (session, va_system).

A single session can have multiple VAs running simultaneously when the study
declares more than one entry in `va_systems:`. The spawner keys every running
process on the composite ``(session_id, va_system_id)`` so the same session can
hold several VAs without confusion.

It does not own the WebSocket collector; that is started separately so a
session created without a VA (questionnaire-only) does not spin one up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from studio.config.schemas import VAConfig, VAVariant
from studio.settings import get_settings

log = logging.getLogger("studio.va_spawner")


def _append_token(url: str, va: VAConfig) -> str:
    """Append a protected VA's access token as a query param.

    The secret is read from the env var named by ``va.token_env`` (never the
    YAML) and appended as ``?<token_param>=<value>`` so BOTH the embedded iframe
    and Studio's server-side health check authenticate. No-op when unset.
    """
    token_env = getattr(va, "token_env", None)
    if not token_env or not url:
        return url
    value = os.environ.get(token_env, "")
    if not value:
        return url
    from urllib.parse import quote
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{va.token_param}={quote(value, safe='')}"


def _append_room(url: str, session_id: str, va: VAConfig) -> str:
    """Append the session's room id so a SHARED external VA serves an isolated
    world per session.

    The room id is the Studio ``session_id`` — unique per participant in
    singleplayer and shared across a multiplayer cohort (they ride the same
    Session) — which is exactly the isolation boundary we want. No-op unless
    ``va.room_per_session`` is set (default true for external VAs).
    """
    if not getattr(va, "room_per_session", False) or not url or not session_id:
        return url
    from urllib.parse import quote
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{va.room_param}={quote(session_id, safe='')}"


@dataclass(slots=True)
class SpawnedVA:
    pid: int
    port: int
    recording_dir: Path
    process: subprocess.Popen
    started_at: datetime
    variant: str
    iframe_url: str
    va_system_id: str
    internal_url: str = ""


def _key(session_id: str, va_system_id: str) -> str:
    return f"{session_id}::{va_system_id}"


class VASpawner:
    """Tracks running VA subprocesses keyed by ``(session_id, va_system_id)``."""

    def __init__(self) -> None:
        self._running: dict[str, SpawnedVA] = {}
        self._used_ports: set[int] = set()
        self._lock = asyncio.Lock()

    # ── public ────────────────────────────────────────────────────────────

    async def spawn(
        self,
        session_id: str,
        va_system_id: str,
        va: VAConfig,
        variant_name: str,
        recording_dir: Path,
    ) -> SpawnedVA:
        """Bring up a VA for this (session, va_system).

        Branches on ``va.compose``:
          - ``compose`` set → ``docker compose -f <file> up -d <service>``,
            with PID inferred from ``docker inspect`` so we can still detect
            liveness via the existing PID-based path.
          - otherwise → ``subprocess.Popen(va.spawn_cmd)`` (default).

        Both branches respect ``va.health_check_url`` and time out if the VA
        doesn't report ready within ``va.spawn_timeout_seconds``.
        """
        # External VAs aren't spawned here, so they don't consume a port.
        if va.external:
            port = 0
        else:
            async with self._lock:
                port = self._allocate_port()
                self._used_ports.add(port)

        variant = va.variants.get(variant_name) or VAVariant()
        recording_dir.mkdir(parents=True, exist_ok=True)

        if va.external:
            spawned = self._spawn_external(
                va=va,
                variant_name=variant_name,
                recording_dir=recording_dir,
                va_system_id=va_system_id,
                session_id=session_id,
            )
        elif va.compose is not None:
            spawned = await self._spawn_compose(
                session_id=session_id,
                va_system_id=va_system_id,
                va=va,
                variant_name=variant_name,
                variant=variant,
                port=port,
                recording_dir=recording_dir,
            )
        else:
            spawned = self._spawn_process(
                va=va,
                variant_name=variant_name,
                variant=variant,
                port=port,
                recording_dir=recording_dir,
                va_system_id=va_system_id,
            )

        if va.health_check_url:
            settings = get_settings()
            health_url = va.health_check_url.format(
                port=port,
                external_base=settings.external_va_base_url,
                external_health_base=settings.external_va_health_base,
                voyager_base=settings.voyager_base_url,
                voyager_health_base=settings.voyager_health_base,
                proactive_base=settings.proactive_base_url,
                proactive_health_base=settings.proactive_health_base,
                variant=variant_name,
            )
            health_url = _append_token(health_url, va)
            timeout_s = min(va.spawn_timeout_seconds, 10) if va.external else va.spawn_timeout_seconds
            try:
                await self._wait_until_healthy(health_url, timeout_s=timeout_s)
            except TimeoutError:
                if va.external:
                    log.warning(
                        "external VA health check did not pass within %ss (%s); "
                        "mounting iframe anyway — the browser loads the VA directly",
                        timeout_s, health_url,
                    )
                else:
                    self._terminate(spawned.process)
                    self._used_ports.discard(port)
                    raise

        self._running[_key(session_id, va_system_id)] = spawned
        return spawned

    def _spawn_external(
        self,
        *,
        va: VAConfig,
        variant_name: str,
        recording_dir: Path,
        va_system_id: str,
        session_id: str,
    ) -> SpawnedVA:
        """No-op 'spawn' for an externally-hosted VA.

        Studio embeds ``iframe_url`` (with ``{external_base}`` filled from
        STUDIO_EXTERNAL_VA_BASE_URL) and never launches a process. Liveness is
        owned by the external service; the stand-in process reports alive.

        The session's room id is appended so a single shared VA instance still
        gives this session its own isolated world (see ``_append_room``). The
        health-check URL deliberately stays room-less — it only probes that the
        host is up and must not spin up a room.
        """
        settings = get_settings()
        iframe_url = va.iframe_url.format(
            port=0,
            variant=variant_name,
            external_base=settings.external_va_base_url,
            external_health_base=settings.external_va_health_base,
            voyager_base=settings.voyager_base_url,
            voyager_health_base=settings.voyager_health_base,
            proactive_base=settings.proactive_base_url,
            proactive_health_base=settings.proactive_health_base,
        )
        iframe_url = _append_room(iframe_url, session_id, va)
        iframe_url = _append_token(iframe_url, va)

        # Same template, but every *_base placeholder resolves to the
        # Docker-network *_health_base instead of the browser-facing host —
        # this is what Studio's own process (health checks, ws_collector)
        # must use, since `external_base` (e.g. localhost:7100) is only
        # reachable from the participant's browser, not from inside another
        # container.
        internal_url = va.iframe_url.format(
            port=0,
            variant=variant_name,
            external_base=settings.external_va_health_base,
            external_health_base=settings.external_va_health_base,
            voyager_base=settings.voyager_health_base,
            voyager_health_base=settings.voyager_health_base,
            proactive_base=settings.proactive_health_base,
            proactive_health_base=settings.proactive_health_base,
        )
        internal_url = _append_room(internal_url, session_id, va)
        internal_url = _append_token(internal_url, va)

        return SpawnedVA(
            pid=0,
            port=0,
            recording_dir=recording_dir,
            process=_ExternalProcess(),
            started_at=datetime.now(timezone.utc),
            variant=variant_name,
            iframe_url=iframe_url,
            internal_url=internal_url,
            va_system_id=va_system_id,
        )

    def _spawn_process(
        self,
        *,
        va: VAConfig,
        variant_name: str,
        variant: VAVariant,
        port: int,
        recording_dir: Path,
        va_system_id: str,
    ) -> SpawnedVA:
        env = os.environ.copy()
        env.update(va.env)
        env["STUDIO_VA_PORT"] = str(port)
        env["STUDIO_VA_RECORDING_DIR"] = str(recording_dir)
        env["STUDIO_VA_SYSTEM_ID"] = va_system_id

        cmd_str = va.spawn_cmd.format(
            port=port,
            recording_dir=str(recording_dir),
            variant=variant_name,
            variant_args=variant.spawn_extra_args,
        )

        process = subprocess.Popen(
            cmd_str,
            shell=True,
            env=env,
            cwd=va.cwd or None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        iframe_url = va.iframe_url.format(
            port=port, variant=variant_name,
            external_base=get_settings().external_va_base_url,
            external_health_base=get_settings().external_va_health_base,
        )
        return SpawnedVA(
            pid=process.pid,
            port=port,
            recording_dir=recording_dir,
            process=process,
            started_at=datetime.now(timezone.utc),
            variant=variant_name,
            iframe_url=iframe_url,
            internal_url=iframe_url,
            va_system_id=va_system_id,
        )

    async def _spawn_compose(
        self,
        *,
        session_id: str,
        va_system_id: str,
        va: VAConfig,
        variant_name: str,
        variant: VAVariant,
        port: int,
        recording_dir: Path,
    ) -> SpawnedVA:
        compose = va.compose
        assert compose is not None  # narrow type
        # Resolve the compose file relative to the VA's cwd (or studio CWD).
        from studio.settings import get_settings
        cwd = Path(va.cwd) if va.cwd else get_settings().data_dir.parent
        compose_path = Path(compose.file)
        if not compose_path.is_absolute():
            compose_path = (cwd / compose_path).resolve()

        env = os.environ.copy()
        env.update(va.env)
        env["STUDIO_VA_PORT"] = str(port)
        env["STUDIO_VA_RECORDING_DIR"] = str(recording_dir)
        env["STUDIO_VA_SYSTEM_ID"] = va_system_id

        args = ["docker", "compose", "-f", str(compose_path)]
        if compose.project:
            args += ["-p", compose.project]
        up = await asyncio.create_subprocess_exec(
            *args, "up", "-d", "--no-recreate", compose.service,
            env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await up.communicate()
        if up.returncode != 0:
            self._used_ports.discard(port)
            raise RuntimeError(
                f"docker compose up failed (exit {up.returncode}): "
                f"{(err or out).decode('utf-8', 'replace')[:400]}"
            )

        # Resolve the container id and read its PID via docker inspect.
        ps = await asyncio.create_subprocess_exec(
            *args, "ps", "-q", compose.service,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        ps_out, _ = await ps.communicate()
        container_id = (ps_out or b"").decode("utf-8").strip().splitlines()[0] if ps_out else ""
        pid = 0
        if container_id:
            insp = await asyncio.create_subprocess_exec(
                "docker", "inspect", "-f", "{{.State.Pid}}", container_id,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            insp_out, _ = await insp.communicate()
            try:
                pid = int((insp_out or b"0").decode("utf-8").strip())
            except ValueError:
                pid = 0

        iframe_url = va.iframe_url.format(
            port=port, variant=variant_name,
            external_base=get_settings().external_va_base_url,
            external_health_base=get_settings().external_va_health_base,
        )
        # The "process" stand-in points at the container PID; stop() will
        # route through _terminate which detects _ComposeProcess and runs
        # `docker compose stop <service>`.
        process = _ComposeProcess(
            compose_args=args, service=compose.service, pid=pid,
        )
        return SpawnedVA(
            pid=pid,
            port=port,
            recording_dir=recording_dir,
            process=process,
            started_at=datetime.now(timezone.utc),
            variant=variant_name,
            iframe_url=iframe_url,
            internal_url=iframe_url,
            va_system_id=va_system_id,
        )

    async def stop(
        self,
        session_id: str,
        va_system_id: str,
        grace_seconds: int | None = None,
    ) -> None:
        info = self._running.pop(_key(session_id, va_system_id), None)
        if info is None:
            return
        grace = grace_seconds if grace_seconds is not None else get_settings().va_shutdown_grace_seconds
        self._terminate(info.process, grace=grace)
        self._used_ports.discard(info.port)

    async def stop_session(self, session_id: str) -> None:
        """Stop every VA running for the given session_id."""
        prefix = f"{session_id}::"
        keys = [k for k in self._running if k.startswith(prefix)]
        for k in keys:
            _, va_system_id = k.split("::", 1)
            await self.stop(session_id, va_system_id)

    async def stop_all(self) -> None:
        for k in list(self._running.keys()):
            session_id, va_system_id = k.split("::", 1)
            await self.stop(session_id, va_system_id)

    def get(self, session_id: str, va_system_id: str) -> SpawnedVA | None:
        return self._running.get(_key(session_id, va_system_id))

    def running_for_session(self, session_id: str) -> dict[str, SpawnedVA]:
        """Return {va_system_id: SpawnedVA} for everything currently running for this session."""
        prefix = f"{session_id}::"
        return {
            k[len(prefix):]: v
            for k, v in self._running.items()
            if k.startswith(prefix)
        }

    def reattach(
        self,
        session_id: str,
        va_system_id: str,
        pid: int,
        port: int,
        recording_dir: Path,
        iframe_url: str,
        variant: str,
        started_at: datetime,
        internal_url: str = "",
    ) -> SpawnedVA:
        """Re-register a VA process that survived a Studio restart.

        We don't have a ``subprocess.Popen`` for the process anymore, so
        ``stop()`` calls fall back to OS-level signals via the PID (see
        ``_terminate_by_pid``). Used by ``session_manager.recover_interrupted_sessions``.
        """
        info = SpawnedVA(
            pid=pid,
            port=port,
            recording_dir=recording_dir,
            process=_DetachedProcess(pid),         # see helper class below
            started_at=started_at,
            variant=variant,
            iframe_url=iframe_url,
            internal_url=internal_url or iframe_url,
            va_system_id=va_system_id,
        )
        self._running[_key(session_id, va_system_id)] = info
        self._used_ports.add(port)
        return info

    # ── helpers ───────────────────────────────────────────────────────────

    def _allocate_port(self) -> int:
        settings = get_settings()
        for port in range(settings.va_port_range_start, settings.va_port_range_end + 1):
            if port in self._used_ports:
                continue
            if _port_is_free(port):
                return port
        raise RuntimeError("no free VA port available in configured range")

    @staticmethod
    async def _wait_until_healthy(url: str, timeout_s: int) -> None:
        deadline = asyncio.get_event_loop().time() + timeout_s
        async with httpx.AsyncClient(timeout=2.0) as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.4)
        raise TimeoutError(f"health check {url} did not return 200 within {timeout_s}s")

    @staticmethod
    def _terminate(process: subprocess.Popen, grace: int = 5) -> None:
        # Detached (reattached) processes don't have a real Popen — fall back
        # to OS-level termination by PID.
        if isinstance(process, _DetachedProcess):
            _terminate_by_pid(process.pid, grace=grace)
            return
        # Compose-driven container: run `docker compose stop <service>`.
        if isinstance(process, _ComposeProcess):
            try:
                process.terminate(grace=grace)
            except Exception:
                pass
            return
        # External VA: Studio doesn't own its lifecycle — nothing to stop.
        if isinstance(process, _ExternalProcess):
            return
        if process.poll() is not None:
            return
        try:
            process.terminate()
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        except Exception:
            pass


class _ComposeProcess:
    """Stand-in for ``subprocess.Popen`` when a VA is started by docker-compose.

    Carries the compose args + service name so ``stop()`` can issue a
    ``docker compose stop <service>`` instead of signalling a PID directly.
    Container PID is exposed so PID-liveness checks still work.
    """

    def __init__(self, compose_args: list[str], service: str, pid: int) -> None:
        self._compose_args = compose_args
        self._service = service
        self.pid = pid

    def poll(self) -> int | None:
        from studio.process import pid_alive
        return None if pid_alive(self.pid) else 1

    def terminate(self, grace: int = 5) -> None:  # noqa: ARG002
        # Best-effort `docker compose stop` (graceful; container keeps its
        # state so the admin can inspect logs afterwards).
        import subprocess as _sp
        try:
            _sp.run(
                self._compose_args + ["stop", "-t", str(max(grace, 1)), self._service],
                check=False, capture_output=True, timeout=max(grace + 5, 10),
            )
        except Exception:
            pass

    def kill(self) -> None:
        import subprocess as _sp
        try:
            _sp.run(
                self._compose_args + ["kill", self._service],
                check=False, capture_output=True, timeout=10,
            )
        except Exception:
            pass

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        return 0


class _ExternalProcess:
    """Stand-in for ``subprocess.Popen`` when the VA is externally hosted.

    Studio doesn't launch or own the process, so it always reports alive and
    its terminate/kill are no-ops. ``pid`` is 0 (never used for signalling).
    """

    pid = 0

    def poll(self) -> int | None:
        return None  # externally hosted — treat as always running

    def terminate(self) -> None:  # noqa: D401
        pass

    def kill(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        return 0


class _DetachedProcess:
    """Stand-in for ``subprocess.Popen`` after a Studio restart.

    Carries only the PID; ``poll()`` returns None while the process is alive,
    a non-zero code when it's gone. The spawner's terminate path branches on
    type and falls back to OS-level signals for instances of this class.
    """

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        from studio.process import pid_alive
        return None if pid_alive(self.pid) else 1

    def terminate(self) -> None:
        _terminate_by_pid(self.pid, grace=0)

    def kill(self) -> None:
        _terminate_by_pid(self.pid, grace=0)

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        return 0


def _terminate_by_pid(pid: int, grace: int = 5) -> None:
    """Best-effort cross-platform stop of a detached PID."""
    from studio.process import pid_alive
    import os, signal, time
    if not pid_alive(pid):
        return
    try:
        if hasattr(signal, "SIGTERM"):
            os.kill(pid, signal.SIGTERM)
        # poll for exit; if still alive after grace, escalate.
        deadline = time.time() + max(grace, 0)
        while time.time() < deadline and pid_alive(pid):
            time.sleep(0.2)
        if pid_alive(pid) and hasattr(signal, "SIGKILL"):
            os.kill(pid, signal.SIGKILL)
        elif pid_alive(pid):
            # Windows fallback
            try:
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
                if handle:
                    ctypes.windll.kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                pass
    except Exception:
        pass


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


va_spawner = VASpawner()

"""Run a tool script, under AutoTool's in-process guard when it is configured.

    python -m autotool.guard path/to/tool.py

Configuration arrives in ``AUTOTOOL_GUARD`` (JSON): ``{"hosts": [...] | null, "protect": [paths]}``.
A PEP 578 audit hook, which the tool's code cannot remove, blocks:
- subprocesses, and loading or calling native code after start-up;
- the OS credential stores (keyring, win32cred, win32ctypes, cffi);
- reading AutoTool's credential files, host MCP configs and /proc/*/environ;
- creating, changing, moving or deleting files outside the temp directory;
- when the tool holds a host-restricted credential, resolving or reaching any other host
  (loopback excepted: it never leaves the machine).

This is a guard, not a jail: native extensions or interpreter bugs can get past an audit hook.
Run AutoTool in a container or VM for a hard boundary (and ``autotool serve --sandbox off``)."""

from __future__ import annotations

import fnmatch
import ipaddress
import json
import logging
import os
import re
import runpy
import socket
import sys
import tempfile
import threading

_BLOCKED_EVENTS = {
    "subprocess.Popen": "starting a subprocess",
    "os.system": "os.system",
    "os.exec": "os.exec*",
    "os.spawn": "os.spawn*",
    "os.posix_spawn": "os.posix_spawn",
    "os.fork": "os.fork",
    "os.startfile": "os.startfile",
    "ctypes.dlopen": "loading native code with ctypes",
    "ctypes.dlsym": "calling native code with ctypes",
}
_BLOCKED_IMPORTS = {"keyring", "win32cred", "win32ctypes", "cffi", "_cffi_backend"}
# File-changing events -> (path argument, dir_fd argument) pairs; each path must lie inside the temp
# directory. dir_fd matters on Linux/macOS, where shutil.rmtree works relative to open directories.
# (os.symlink's first argument is the link's *target*; reads through links are caught by realpath.)
_FILE_CHANGES = {
    "os.remove": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),
    "os.link": ((0, 2), (1, 3)),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "os.chmod": ((0, 2),),
    "os.chown": ((0, 3),),
    "os.mkdir": ((0, 2),),
    "os.rmdir": ((0, 1),),
    "os.utime": ((0, 3),),
    "shutil.rmtree": ((0, 1),),
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC | getattr(os, "O_TEMPORARY", 0)
_PROC_ENVIRON = re.compile(r"^/proc/[^/]+/(task/[^/]+/)?environ$")
_state = threading.local()  # per-thread: asyncio resolves names in executor threads


def host_allowed(host: str, patterns: list[str]) -> bool:
    host = host.lower().rstrip(".")
    return any(fnmatch.fnmatchcase(host, p.lower().rstrip(".")) for p in patterns)


def _deny(what: str) -> None:
    raise PermissionError(f"blocked by AutoTool's guard: {what}")


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.split("%")[0])
        return True
    except ValueError:
        return False


def _is_loopback(value: str) -> bool:
    # Loopback never leaves the machine, and asyncio needs it (its Windows event loop wakes itself
    # through a 127.0.0.1 socket pair). Allowlists guard against sending keys *off* the machine.
    try:
        return ipaddress.ip_address(value.split("%")[0]).is_loopback
    except ValueError:
        return value.lower().rstrip(".") == "localhost"


def _fd_dir(fd: int) -> str | None:
    """The directory an open descriptor refers to, or None if the platform can't say."""
    try:
        if sys.platform.startswith("linux"):
            return os.readlink(f"/proc/self/fd/{fd}")
        if sys.platform == "darwin":
            import fcntl

            return os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0"))
    except OSError:
        pass
    return None


def _real(path: object, dir_fd: object = None) -> str | None:
    """Resolved path; None for a file descriptor (checked when it was opened); "" if unknowable."""
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    path = os.fsdecode(path)
    if isinstance(dir_fd, int) and not os.path.isabs(path):
        base = _fd_dir(dir_fd)
        if base is None:
            return ""  # relative to a directory we cannot name: treat as outside temp
        path = os.path.join(base, path)
    return os.path.normcase(os.path.realpath(path))


def install(config: dict) -> None:
    hosts: list[str] | None = config.get("hosts")
    protect = {_real(p) for p in config.get("protect") or []}
    temp = _real(tempfile.gettempdir()) + os.sep
    allowed_ips: set[str] = set()

    def in_temp(real: str | None) -> bool:
        return real is None or (real != "" and real.startswith(temp))

    def check_name(host: object) -> None:
        host = host.decode() if isinstance(host, bytes) else host
        if not isinstance(host, str) or _is_ip(host) or _is_loopback(host):
            return  # IPs are checked when used
        if not host_allowed(host, hosts):
            _deny(f"network access to {host} (this tool's credentials are limited to: {', '.join(hosts)})")
        _state.resolving = True  # the lookup below raises resolver events again, on this thread
        try:
            allowed_ips.update(str(info[4][0]) for info in socket.getaddrinfo(host, None))
        except OSError:
            pass
        finally:
            _state.resolving = False

    def check_ip(ip: object) -> None:
        ip = str(ip)
        if ip not in allowed_ips and not _is_loopback(ip) and not host_allowed(ip, hosts):
            _deny(f"network access to {ip} (this tool's credentials are limited to: {', '.join(hosts)})")

    def hook(event: str, args: tuple) -> None:
        if event in _BLOCKED_EVENTS:
            _deny(_BLOCKED_EVENTS[event])
        elif event == "import" and args[0].split(".")[0] in _BLOCKED_IMPORTS:
            _deny(f"importing {args[0]}")
        elif event == "open":
            path, mode, flags = args
            real = _real(path)
            if real is None:
                return
            if real in protect or _PROC_ENVIRON.match(real.replace("\\", "/")):
                _deny(f"reading {os.fsdecode(path)}")
            writing = (mode and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & _WRITE_FLAGS)
            if writing and not in_temp(real):
                _deny(f"writing {os.fsdecode(path)} (tools may only write to the temp directory)")
        elif event in _FILE_CHANGES:
            for i, fd_i in _FILE_CHANGES[event]:
                dir_fd = args[fd_i] if fd_i is not None and fd_i < len(args) else None
                if i < len(args) and not in_temp(_real(args[i], dir_fd)):
                    _deny(f"{event} on {os.fsdecode(args[i])} (tools may only change files in the temp directory)")
        elif hosts is None or getattr(_state, "resolving", False):
            return
        elif event in ("socket.getaddrinfo", "socket.gethostbyname"):
            check_name(args[0])
        elif event in ("socket.gethostbyaddr", "socket.getnameinfo"):
            target = args[0][0] if isinstance(args[0], tuple) else args[0]
            if not _is_ip(str(target)):
                check_name(target)
            else:
                check_ip(target)
        elif event in ("socket.connect", "socket.sendto", "socket.sendmsg") and len(args) > 1 and isinstance(args[1], tuple):
            check_ip(args[1][0])

    sys.addaudithook(hook)


def main() -> None:
    raw = os.environ.pop("AUTOTOOL_GUARD", None)  # absent: the sandbox is off, run the tool unguarded
    # MCP servers log a failing tool's traceback but no longer configure logging themselves; send it
    # to stderr, where the verifier (and its repair loop) reads it.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    if raw is not None:
        # The tool runtime loads native code (ctypes) while importing, the server's constructor may
        # too (console and telemetry support), and httpx2's first client loads the OS certificate
        # store (truststore: crypt32.dll on Windows). Let it all happen before sealing.
        import httpx2
        from mcp.server.mcpserver import MCPServer

        MCPServer("autotool-guard-warmup")
        httpx2.Client().close()
        install(json.loads(raw or "{}"))
        if sys.platform == "win32":
            # The default proactor loop connects via ConnectEx, which raises no socket.connect audit
            # event, so an IP literal from async code would bypass the allowlist. The selector loop
            # connects through socket.connect, which the hook sees. Known gap: code that builds a
            # ProactorEventLoop itself still bypasses this; a container closes it.
            import asyncio
            import warnings

            with warnings.catch_warnings():  # event loop policies are deprecated from Python 3.14
                warnings.simplefilter("ignore", DeprecationWarning)
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()

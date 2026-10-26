# Bundled Everything search

The Windows x64 application includes the official Everything executable, SDK, and ES client in `vendor/everything/`. A fresh portable distribution can search without a separate Everything installation. The application starts its own hidden instance on demand; it does not install a service, request elevation, alter file associations, or connect to an existing user instance by default.

## Components and redistribution

The pinned components are Everything **1.4.1.1032 x64 multilingual portable**, the official **Everything SDK**, and **ES 1.1.0.38 x64**. Downloads come from [voidtools Downloads](https://www.voidtools.com/downloads/). Everything is freeware; the full application is not open source. Its [redistribution license](https://www.voidtools.com/License.txt), including third-party notices, is preserved as `LICENSE-Everything.txt`. The SDK's source copyright and permission notice and ES's MIT license are preserved in `LICENSE-SDK.txt` and `LICENSE-ES.txt`.

`scripts/bundle_everything.py` pins the SHA-256 of every downloaded archive and the three executable payloads. The portable archive pin was checked against the official versioned SHA-256 list. The SDK and ES pins record the official HTTPS downloads; they are not presented as separately signed release attestations. A changed archive fails validation until a maintainer reviews and updates the pins. TLS certificate verification remains enabled.

`manifest.json` records versions, original URLs, archive hashes, and hashes of extracted files. The distribution also retains the SDK API and IPC headers and C source. Keep the whole component directory, including licenses and manifest, when redistributing. Binaries and the download cache are gitignored; the reproducible bundling script is tracked.

## Scoped snapshot index

`learning_ext.agent.everything_runtime.ensure_started(root=...)` accepts a local directory, excluding a whole drive and network shares. It enumerates names and metadata into an official UTF-8 EFU file list, then starts the real Everything executable to index that list. EFU is an official supported index format; the required filename column and optional metadata columns are described in [File Lists](https://www.voidtools.com/support/everything/file_lists/).

The snapshot skips symbolic links, junctions, other reparse points, nested `.git`, `.hg`, `.svn`, `.venv`, `venv`, `node_modules`, `__pycache__`, `.pytest_cache`, system directories, and its own index cache. It reads no file contents. Scope is rechecked while enumerating. A snapshot exceeding 25,000 entries, two seconds, or 12 directory levels is rejected rather than published as complete. Unreadable or changing paths also prevent publishing a new snapshot; the caller can use the bounded native search fallback.

This strategy is deliberate: Everything 1.4 folder indexing [follows junctions](https://www.voidtools.com/forum/viewtopic.php?t=6189). The runtime therefore leaves native volumes and `folders` disabled and sets only `filelists` in the instance's INI. It does not rely on an undocumented junction switch. HTTP, ETP, search history, and run history are disabled. Settings use the documented [INI configuration](https://www.voidtools.com/support/everything/ini/).

Results expose `index_mode="scoped_snapshot"`, `snapshot_at`, and `snapshot_complete`. Complete means the allowed snapshot scope was enumerated within those limits, including the stated exclusions. It does not mean a live or whole-computer inventory. Snapshots expire after 60 seconds; the next request rebuilds that scope and restarts its instance. ES may still be waiting for Everything to finish loading. An unavailable or empty index is not evidence that a file or application is absent.

## Query boundary

The bundled SDK does not export a named-instance setter. Its normal IPC connection targets the default Everything window. The application uses the official ES command-line client with `-instance` for its own named instance, preserving the user's independently installed Everything. See the official [SDK documentation](https://www.voidtools.com/en-us/support/everything/sdk/) and [named-instance SDK discussion](https://www.voidtools.com/forum/viewtopic.php?t=8338).

`agent/everything.py` queries a bounded number of full paths through ES. Output is exported to a private temporary JSON file and decoded as UTF-8; plain console output can use the Windows locale encoding. Query arguments are passed as an argument list, not a shell command. Space characters are encoded within the regular expression so Everything cannot reinterpret them as separate search terms. `agent/search.py` verifies every returned path, scope, type, depth, and exclusion before using it.

`LE_EVERYTHING_DISABLED=1` disables the accelerated index. An administrator may explicitly set `LE_EVERYTHING_DLL` to an absolute local DLL for an already running default instance; this legacy SDK path runs in a bounded subprocess and rejects a nonempty `LE_EVERYTHING_INSTANCE`. Missing payloads, invalid hashes, startup failures, incomplete snapshots, query timeouts, and no verified hits retain a reason and fall back to the bounded native filename search. File-content search remains separate.

## Cache and lifecycle

Index state lives under `kotaemon/ktem_app_data/everything/<scope-hash>/`, alongside the application's local data. A scope hash is stable across restarts; per-process instance names remain unique. An OS file lock prevents two backend processes from modifying the same scope cache. A cache already in use yields a fallback rather than touching another process.

At most four owned instances run at once. A new scope replaces the least recently used owned instance after it exits. Shutdown sends an instance-specific exit request, then terminates only that recorded child if necessary. A Windows Job Object with `KILL_ON_JOB_CLOSE` binds all owned Everything children to the backend process, including when the desktop launcher forcibly terminates the backend. If Job Object attachment fails, the runtime stops the child and declines to use it. `atexit` handles normal shutdown; the Job Object supplies the forced-exit guarantee. No process-name-wide termination is used.

## Build and verification

Run from the repository root using the application's Python:

```powershell
& kotaemon/.venv/Scripts/python.exe scripts/bundle_everything.py
& kotaemon/.venv/Scripts/python.exe scripts/bundle_everything.py --verify
```

`pack_portable.bat` verifies or obtains the component before assembling the distribution, then copies the whole `vendor/everything` directory. The application performs no first-search download. A build machine needs official downloads once, or a validated cache supplied through `--cache`.

Unit checks cover payload tampering, scoped enumeration, dependency exclusions, snapshot budgets, instance reuse, cache stability, expiry, capacity replacement, and failed lifecycle protection. The opt-in Windows integration check uses the actual downloaded executable and ES, creates Chinese filenames and a junction to a separate fixture, checks that only allowed files are found, and forcibly terminates its test backend to verify that the owned Everything child exits:

```powershell
$env:LE_EVERYTHING_INTEGRATION = '1'
& kotaemon/.venv/Scripts/python.exe -m pytest tests/test_everything_runtime.py -q
```

Verified on this Windows host with the pinned official payload. The integration check does not install or stop a user's Everything service. Full portable application assembly is separate from component validation and was not run as part of this change.

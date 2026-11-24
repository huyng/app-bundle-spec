---
title: App Bundle Layout Specification
short_title: App Bundle Layout
eyebrow: Filesystem convention
version: 1.1
description: "A filesystem convention for self-contained applications: one directory per app, copy to install, delete to uninstall."
lede: >
  A filesystem convention for self-contained applications. An app is one directory. Copying it is installation; deleting it is uninstallation. The same layout applies to desktop apps, command-line tools, and daemons, at user or system scope.
---

## 1. App root

Every app has exactly one root directory. Executables, configuration, resources, caches, runtime files, etc, all live under this root. They are not spread across many directories in the standard filesystem heirarchy.

### 1.1 Scope

Apps are installed within a scope: either system-wide or on a per-user basis.

::: table mono
| Scope | App root | Owner |
| --- | --- | --- |
| Per-user | ~/.apps/\<id\>/ | the user |
| System | /opt/apps/\<id\>/ | root or a dedicated service user |
:::

- The internal layout ([§1.2](#s1.2)) is identical at both scopes and at any other target. The two paths above are an installer's defaults ([§6](#s6)); the app never computes them ([§3](#s3)).
- Scope is an installation decision. The app is never told its scope and does not need it, because everything it resolves comes from [§3](#s3). The manifest does not record it.

### 1.2 Internal layout

```tree
<app-root>/
├── app.toml          # manifest (required); describes the root
├── contents/         # immutable tree (required); replaced wholesale on upgrade
│   ├── bin/          #   executed or exposed files        (convention)
│   ├── lib/          #   libraries and app code           (convention)
│   └── resources/    #   read-only assets                 (convention)
├── data/             # persistent mutable data
│   └── config.json   #   settings                         (convention)
├── cache/            # regenerable data
└── run/              # ephemeral; cleared or ignored on startup
```

::: note
**The interiors of `contents/` and `data/` are conventions, not requirements.** The files shown under each are only examples of a typical shape. Three facts about `contents/` are normative: it exists, nothing in it is written at runtime, and if `app.toml` declares an `entrypoint` that path resolves to an executable file inside it. The `bin/`, `lib/`, `resources/` split is the recommended shape for bundles that need it, and nothing outside the app may depend on it.
:::

- `app.toml` is at the root because it describes the root. It is replaced on upgrade ([§7](#s7)) and is never written at runtime.
- `contents/` is the tree that ships. It is never modified at runtime, and it is self-contained: dependencies are resolved when the tree is built and shipped inside it, and nothing is fetched when the app starts. A tree that bakes an absolute install prefix into its files is non-conforming. A launcher may compute absolute paths at runtime ([§5.1](#s5.1)); a build may not write them in.
- `data/`, `cache/`, and `run/` are created by the app on first use.
- The names under `data/` are examples, not a layout. An app that keeps one SQLite file, a directory per document, or nothing at all conforms equally; only the directory itself and who may write to it are normative.

### 1.3 Modes

::: table mono
| Path | Per-user | System |
| --- | --- | --- |
| root | 0700 | 0750, owned by the service user |
| app.toml | 0644 | 0644 |
| contents/ | 0755, read-only at runtime | 0755, read-only at runtime |
| data/ | 0700 | 0750 |
| cache/ | 0700 | 0750 |
| run/ | 0700 | 0700 |
:::

If a process outside the app's group must reach something in `run/`, set the root to `0751` (traverse-only) and `run/` to `0755`. A `0755` `run/` under a `0750` root is unreachable and therefore an error. Both changes are pointless for a per-user app, where the root is `0700`.

### 1.4 Write discipline

An app writes to two kinds of places: its own, whose location the layout fixes, and the user's, whose location the user names. This section governs what the app writes on its own initiative.

::: table
| Write target | Allowed |
| --- | --- |
| a mutable directory in the app root | yes |
| a mutable directory a supervisor relocated ([§3.1](#s3.1)) | yes |
| a path the user names at runtime | yes |
| any other path outside the root | no |
| inside `contents/` | never |
:::

- An app is **confined** when it writes nothing outside its mutable directories and the paths the user names. Deleting the root then deletes every trace of it, unless a supervisor relocated a mutable directory ([§3.1](#s3.1)).
- **A path the user names at runtime is not governed here.** A document passed on the command line, a file chosen in a dialog, a directory an export is written into — these are the user's writes, made at the user's direction, and the discipline allows them. Reopening the document the user last edited is still user-directed. Copying it into a backup directory on a schedule is not: a write the app makes without being asked is not allowed.
- This describes writes only. Reads, network access, and what the app does with the bytes are outside this section.

::: note
**An app that needs a fixed location outside its root has one option: the user names it.** A document library, an integration point another program reads, a folder the user browses — each is a path passed at runtime, or a location the user chooses in the app, not a path the app asserts in its manifest. That is what keeps the rule auditable: nothing outside the root is written unless a person asked for it in that run.
:::

## 2. Manifest (app.toml)

TOML, at the app root. Unknown keys are ignored. All paths in the manifest are relative to the contents directory (`contents/`), regardless of the manifest's own location. Absolute paths are invalid.

The manifest describes the root, so the copy that ships is not always the copy that is authored. A manifest in a source tree MAY be incomplete, and an installer MAY generate the fields the source could not know ([§6](#s6)).

### 2.1 Required fields

::: table
| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Unique identifier ([§2.3](#s2.3)). Stable across versions. Names the app root. |
| `name` | string | Human-readable name. |
| `version` | string | Non-empty version string, opaque to this specification. MUST be present in an installed root; a source tree's manifest MAY omit it, and the installer then supplies it from the revision installed ([§6](#s6)). Display metadata only: see [§2.5](#s2.5). |
:::

### 2.2 Optional fields

::: table
| Field | Type | Description |
| --- | --- | --- |
| `entrypoint` | string | Path to the executable, relative to `contents/`. MUST resolve to an executable file. It runs in the foreground ([§5](#s5)). A bundle that declares none is installed and exposed to nothing. |
| `icon` | string | Path to an icon, relative to `contents/`. |
| `description` | string | Short description. |
| `license` | string | SPDX license identifier. |
| `homepage` | string | URL. |
:::

### 2.3 Identity (`id`)

- MUST be lowercase, dot-separated, at least two segments, and filesystem-safe: `a–z`, `0–9`, `.`, `-`, `_`. No `/`, no spaces, no leading `.`, no `..`, no empty segment.
- SHOULD be a namespace the author controls: a domain in reverse-DNS (`org.example.monitord`) or a platform handle (`github.alice.jsonfmt`).
- MUST be stable across versions. Changing it orphans the app root and all its data.
- **`id` is self-asserted and unverified.** It is a namespace for paths and display, not an identity or authorization claim. Conventions reduce collisions; they do not prevent them. Hosts and installers MUST NOT treat `id` as proof of authorship.

### 2.4 Examples

```app.toml
id = "org.example.notepad"
name = "Notepad"
version = "1.2.0"
entrypoint = "bin/notepad"
icon = "resources/icon.svg"
```

```app.toml
id = "org.example.monitord"
name = "monitord"
version = "0.4.2"
entrypoint = "bin/monitord"
```

Both are confined.

Both declare a `version` because they are installed roots. The same manifest in a source tree may leave the line out and let the installer fill it in.

The format does not distinguish app types. Desktop apps, command-line tools, and daemons use the same manifest and the same layout. How `entrypoint` is run — interactively, supervised, socket-activated — is outside this specification.

`entrypoint` may be a native executable, a script with an interpreter directive, or a launcher that sets up an interpreted runtime and `exec`s the interpreter. The manifest does not distinguish these; the launcher is the sanctioned mechanism ([§5.1](#s5.1)).

### 2.5 The version is not a compatibility signal

`version` says which build is installed and nothing more. It is display metadata for listing installed apps, and for a human reading `app.toml`.


## 3. Runtime path resolution

The app root is derived, not configured. An installed app always knows where it is, because its entrypoint is inside `contents/` ([§11.1](#s11.1)): the root is the nearest ancestor of the entrypoint's own real location that holds `app.toml`. Nothing needs to be passed in and nothing needs to be compiled in.

1. `$APP_ROOT`, when set and non-empty, is the app root. The app MUST resolve symlinks and use the real path, and MUST fail with a clear message when that path holds no `app.toml`. An invented root would scatter the app's writes into an unrelated directory.
2. Otherwise the app root is the nearest ancestor of the running program's real location that holds `app.toml`. A native executable starts from `/proc/self/exe` or its equivalent. An interpreted app starts from its own resolved location: the launcher walks up from its real path and exports `$APP_ROOT` ([§5.1](#s5.1)), or the code does the same from its module's resolved path. If no ancestor holds `app.toml`, the app MUST fail with a clear message rather than fall back to a guess.

The contents directory is `<app-root>/contents/`. The manifest is `<app-root>/app.toml`. Every file the app reads at runtime is found relative to it: a file at `<path>` inside `contents/` is read as `contents_dir()/<path>`. The shape of `contents/` is the app's own choice ([§1.2](#s1.2)).

::: note
**Why an environment variable at all.** A native executable finds its own root from `/proc/self/exe`. An interpreter cannot: the running program is `python3`, and `/proc/self/exe` is the interpreter, not the app. The launcher bridges that gap by exporting `$APP_ROOT`. An installed app of either kind runs correctly with `$APP_ROOT` unset; launchers and development harnesses set it when the tree they run is not a real tree, such as a symlinked `contents/` or a temporary root.
:::

### 3.1 Relocated mutable directories

Each mutable directory MAY be relocated individually by the variable that names it ([§3.2](#s3.2)). When used, the app treats the target as its mutable directory. This exists for supervisors that mandate `/var/lib/<id>`, `/var/cache/<id>`, and `/run/<id>`. Relocated directories are invisible to the installer: nothing in the manifest records them, and purging them is the supervisor's business, not the installer's.

### 3.2 Environment variables

These four are the whole of the specification's environment. Each is an absolute path and is optional; an installed app runs correctly with none of them set.

::: table mono
| Variable | Sets | When unset |
| --- | --- | --- |
| `$APP_ROOT` | the app root | derived from the entrypoint's real location ([§3](#s3)) |
| `$APP_DATA_DIR` | `data/` | `<app-root>/data/` |
| `$APP_CACHE_DIR` | `cache/` | `<app-root>/cache/` |
| `$APP_RUN_DIR` | `run/` | `<app-root>/run/` |
:::

- A value that is set but empty counts as unset, matching the behaviour of an unset variable in most shells.
- `$APP_ROOT` is an override, not a requirement: it exists for launchers ([§5.1](#s5.1)), exposure wrappers ([§6.1](#s6.1)), and development harnesses whose tree is not a real one. An app MUST still work with it unset, and MUST fail clearly when it is set to a directory holding no `app.toml`.
- Nothing else in the environment is this specification's to define. Variables an app invents for its own use are its own; variables a runtime needs are the runtime's, and the launcher sets them ([§5.1](#s5.1)).
- Environment variables are not a configuration mechanism. Nothing in `app.toml` maps to an environment variable, and nothing here maps to a manifest field. Settings are the app's own business, in `data/` ([§4](#s4)).

## 4. Mutable directories

::: table mono
| Purpose | Path | Lifetime | Safe to delete |
| --- | --- | --- | --- |
| Data | \<app-root\>/data/ | permanent | no (loses user data) |
| Cache | \<app-root\>/cache/ | until cleaned | yes (loses time only) |
| Run | \<app-root\>/run/ | process/session | yes (dead already) |
:::

The three directories are the complete set of roles that mutable data can play, on two axes:

::: table
|  | Regenerable | Not regenerable |
| --- | --- | --- |
| **Session-scoped** | `run/` | — (incoherent) |
| **Cross-session** | `cache/` | `data/` |
:::

The fourth quadrant is empty by definition: anything that must survive a restart and cannot be rebuilt is cross-session, not session-scoped. The three roles are therefore the minimum set, and no one of them can be dropped without collapsing an axis. The directories themselves are created only as an app needs them.

- The app creates these on first use. An app that needs only `data/` is conforming and never creates the other two.
- `run/` MUST be cleared or ignored on every startup, so its persistence across reboot is irrelevant. Supervisors that remove it on stop (e.g. systemd's `RuntimeDirectory=`) provide a stronger guarantee; apps MUST NOT depend on that.
- `data/` survives reboot, logout, crashes, and upgrades. It is removed only on explicit purge. Its internal structure is the app's own and is opaque to everything else.
- `cache/` may be deleted at any time without loss of user data. Its internal structure is the app's own.

::: note
**What `data/` is.** It holds everything the app persists: settings, local databases, indexes, tokens, history, and any files whose lifecycle the app owns. It is the app's durable state, and it is the reason uninstall has two modes (a plain uninstall keeps it; a purge does not).

It is not a general-purpose home for user documents. An app that manages files the user considers theirs (notes, projects, photos) SHOULD store them where the user chooses, naming a path at runtime ([§1.4](#s1.4)). Files in `data/` are expected to be backed up and restored with the app root, not browsed by the user.
:::

## 5. In-code convention

Apps SHOULD centralize path logic in one small module:

- `app_root()` — per [§3](#s3).
- `contents_dir()` — `app_root()/contents/`.
- `data_dir()`, `cache_dir()`, `run_dir()` — per [§4](#s4), created on demand with the modes of [§1.3](#s1.3).

`entrypoint` runs in the foreground. Apps MUST NOT self-daemonize (no fork/setsid/double-fork).

### 5.1 Launchers

An interpreted app ships a launcher at `entrypoint`. The launcher is a script with an interpreter directive, owned by the app, and is responsible for:

- deriving `APP_ROOT` from its own resolved path when it is not already set;
- putting `contents/lib/` on the runtime's search path;
- redirecting any runtime bytecode or compilation cache into `cache/`;
- `exec`ing the interpreter so the process is the app, not a shell parent.

The launcher is the only file that must be executable in an interpreted bundle. See [Appendix B](#appb) for examples.

Reference modules per language: [Appendix A](#appa).

## 6. Installation

Installation produces a conforming app root ([§1](#s1)). How the installed files were obtained is outside this specification: an installer MAY accept a `.tar.gz` bundle, a plain directory, a git checkout, or any other source layout, provided what it produces is an app root.

- The app's files go in `contents/`; the manifest goes at the root. Because manifest paths resolve relative to `contents/` ([§2](#s2)), a source tree whose manifest sits beside its files is installed by moving the manifest up to the root and the rest down into `contents/`. That is the only transform a minimal installer needs.
- An installer MAY generate fields the source tree could not know. `version` is the usual case: it is normally the revision that was installed ([§2.1](#s2.1)).
- An installer SHOULD check the result before exposing it: `app.toml` present at the root with valid required fields, and, when one is declared, an executable `entrypoint` inside `contents/`. This is the test of [§11.1](#s11.1), applied to whatever it just built.
- In steady state the root holds `app.toml`, `contents/`, and whichever mutable directories exist. An installer MAY use temporary names in the root while swapping trees ([§7.1](#s7.1)); none may survive a completed install or upgrade.
- An installer MUST preserve the executable bits and symlinks it finds in the tree, so that a declared `entrypoint` is an executable file inside `contents/`.
- There are **no install-time scripts**. First-run setup is the app's job.
- Menu entries and MIME registration are out of scope. Hosts MAY derive them from `app.toml`; nothing requires it.

::: table mono
| Scope | App root | Entry exposed as |
| --- | --- | --- |
| Per-user | ~/.apps/\<id\>/ | ~/.local/bin/\<entrypoint-name\> symlink or wrapper |
| System | /opt/apps/\<id\>/ | /usr/local/bin/\<entrypoint-name\> symlink or wrapper |
:::

Scope is an installation decision, not a property of the bundle. The same tree installs at either scope; the installer takes the scope from the target it was given, and the manifest says nothing about it. At system scope the installer therefore also writes the wrapper of [§6.1](#s6.1).

### 6.1 Exposure

The exposed entrypoint may be a symlink to `contents/<entrypoint>` or a wrapper script that sets `APP_ROOT` and `exec`s it. A symlink is enough for any conforming entrypoint at either scope, because the entrypoint finds the root from its own location ([§3](#s3)). A wrapper is what a host writes when it has something to add — a relocated mutable directory ([§3.1](#s3.1)), a chosen interpreter — and it then sets `$APP_ROOT` as well.

## 7. Upgrading

An upgrade replaces `contents/` and `app.toml` and MUST NOT modify `data/`, `cache/`, or `run/`.

### 7.1 The swap

The new tree is assembled somewhere other than `contents/` and moved into place whole, on the same filesystem, so that `contents/` is always either the old tree or the new one and never a mixture. Two `rename()` calls — old tree aside, new tree in — satisfy this; where available, `renameat2(RENAME_EXCHANGE)` does it in one step. `app.toml` is replaced as a single file, never edited in place.

A swap that fails leaves the previous tree in place.

### 7.2 Rules

- The installer MUST refuse to upgrade when the new manifest's `id` differs from the directory name.
- The installer MUST NOT touch `data/`, `cache/`, or `run/`. Data migration is the app's responsibility.
- The installer MUST NOT restart daemons. Daemons pick up the new tree when supervision restarts them.

### 7.3 Data migration

Apps that persist structured data MUST maintain a migration path, and SHOULD record a schema version marker in `data/` (conventionally `data/version`).

- On startup, the app compares the marker against the version its code expects and migrates forward if needed.
- Downgrade safety is the app's responsibility: it detects too-new data via the marker and either migrates backward or refuses to start with a clear message.

### 7.4 Running processes

- **Native executables.** On Linux, `rename()` over a running executable's path is safe: the running process keeps the old inode until it exits, so new launches get the new tree while the old one drains away.
- **Interpreted apps.** The old-inode guarantee does not apply. A running interpreter reads `contents/` lazily, so an upgrade during execution can mix old in-memory code with new files on disk. Upgrading a running interpreted app is unsafe. Interactive apps SHOULD detect that their tree changed (for example, by comparing a build identifier recorded at startup) and refuse to continue or offer to restart. Apps that cannot do this MUST document that they may only be upgraded while stopped, because an installer cannot see what is running.
- **Daemons.** The installer leaves the new tree in place and lets supervision restart the service on its own schedule. Restarts remain under the administrator's control.

## 8. Uninstallation

An uninstall removes an installation and nothing else. There are two modes: a plain uninstall, which keeps `data/`, and a purge, which does not. Deleting the app root by hand is a purge; the plain uninstall is the root minus `data/`.

### 8.1 Order

An uninstall proceeds in this order:

1. The exposure ([§6.1](#s6.1)), when it points into this root.
2. `contents/`, `cache/`, and `run/`.
3. `app.toml`.
4. `data/`, on purge only.
5. The root directory itself, once it is empty.

Each step leaves a state that can be read: nothing is exposed into a tree that has lost its executable, and nothing still enumerates as an installed app once `contents/` is gone. An uninstall interrupted at any point therefore leaves either a working installation or a root that is no longer one.

### 8.2 Rules

- An installer MUST NOT remove a directory that holds no `app.toml`. A missing manifest means there is no installation to remove: a leftover `data/`, a mistyped `<id>`, or an unrelated directory.
- Purge MUST be an explicit choice. No default uninstall removes `data/`.
- A relocated mutable directory ([§3.1](#s3.1)) lies outside the root, and removing it is the supervisor's business, not the installer's.
- Uninstall does not stop the app. A running process keeps its executable, so `contents/` can be removed while it runs; an interpreted app reads its tree lazily and may fail midway ([§7.4](#s7.4)). That is a consequence of uninstalling a running app, not a condition the installer can prevent.
- When nothing is installed for `<id>`, an installer SHOULD report that and change nothing.

What a plain uninstall leaves is `data/` alone. That is not an app root: it has no manifest, so a host that enumerates installed apps does not see it, and installing that `<id>` again adopts it.

## 9. Relationship to other formats

- **macOS `.app`.** The closest structural analogue, and the source of the name: `Contents/` plays the role of `contents/`, `Info.plist` that of `app.toml`, and `CFBundleIdentifier` that of `id`. macOS keeps mutable data *outside* the bundle (`~/Library/Application Support/<id>/`, `~/Library/Caches/<id>/`) because the bundle is code-signed and the seal covers `Contents/`. This format internalizes mutable data because the root, not the bundle, is the unit: the point is that deleting the root is a complete uninstall. macOS's externalization is why uninstalling a Mac app leaves a dozen directories behind.
- **FHS / Debian / RPM.** These install a diff against `/` and bake absolute paths at build time, scattering an app across `/usr`, `/etc`, `/var/lib`, `/run`. This format gives each app a single root with the same internal shape at every scope. A system package MAY wrap a conforming app by extracting it intact to `/opt/apps/<id>/`; it MUST NOT split the tree across FHS directories. Where a supervisor mandates FHS placement for mutable data, [§3.1](#s3.1)'s per-directory overrides express it.
- **systemd's `StateDirectory=`, `CacheDirectory=`, `RuntimeDirectory=`.** The same three roles, externally managed. A generated unit file can express this layout in four lines, and under `ProtectSystem=strict` those directives are also the write whitelist. This is the strongest external argument for the taxonomy. Note that `RuntimeDirectory=` is removed on stop, which is stronger than "cleared on startup."
- **Homebrew.** A keg is the closest structural match to `contents/`, but keg state lives in a shared prefix `var/`, which is why uninstall leaves data behind and needs per-formula cleanup stanzas. Homebrew also patches absolute paths at install time; this format requires no patching because resolution is runtime-relative.
- **Nix.** A store path is the purest immutable-tree model, and generation symlinks are a cleaner atomic-swap mechanism than the two-`rename()` procedure here. Nix bakes absolute store paths into binaries, which is what makes trees non-relocatable; this format goes the other way and forbids baked prefixes.
- **Python wheels.** A wheel is a ZIP of a package plus its `.dist-info/`, which does the job of `app.toml`: `METADATA`, `entry_points.txt`, `RECORD`. But it installs *into* a shared `site-packages`, so uninstall is a list of scattered files rather than one directory, and it has no `data/`. Its `RECORD` is the hash list this format lacks.
- **Containers and sandbox packages.** macOS/iOS app containers, Android's per-package `/data/data/<pkg>/`, and Windows MSIX package containers all internalize mutable data and enforce the root as a unit. They enforce it with the kernel; this format enforces it with convention ([§11.2](#s11.2)).
- **Flatpak / Snap / AppImage.** Runtimes with sandboxing and their own integration conventions. This format is layout only.

## 10. What this specification does not define

- **The interior of `contents/` and `data/`.** Both are opaque to everything but the app. Tools MUST NOT depend on internal structure. The `bin/`, `lib/`, `resources/` split is a recommendation.
- Menu entries, icon themes, MIME registration, sandboxing, supervision, autostart, or updates beyond [§7](#s7).
- Daemon lifecycle: supervision, start and stop, restart policy.
- Signing, dependency resolution, repositories, or the source layouts an installer accepts ([§6](#s6)).

## 11. Conformance

### 11.1 An app

An app conforms if:

1. Its root matches [§1.1](#s1.1) and contains `app.toml` and `contents/` per [§1.2](#s1.2).
2. Its `app.toml` contains the required fields of [§2](#s2) with valid values, and `id` satisfies [§2.3](#s2.3).
3. If it declares an `entrypoint`, that path resolves to an executable file inside `contents/`.
4. It resolves paths per [§3](#s3) and uses storage per [§4](#s4).
5. If it declares an `entrypoint`, it runs in the foreground and does not self-daemonize.
6. It writes on its own initiative only inside its mutable directories ([§1.4](#s1.4)). Paths the user names at runtime are written as given and are not a conformance question.

### 11.2 The confinement test

Make two fresh directories: an app root, holding the bundle's `app.toml` and `contents/`, and a `home/` holding one marker file. Set `APP_ROOT` to the root and `HOME` to `home/`, and give the app no outside path to write to. Run it once that way, and once with `$APP_ROOT` unset and through a symlink to its entrypoint, so that it must find the root from its own location ([§3](#s3)). Both runs MUST resolve to the same root. Afterwards the marker MUST be unchanged, and the two directories MUST hold nothing beyond what was put there.

This is the mechanical statement of confinement, and the test that catches the `~/.<name>` habit. Because it measures what the app does on its own, a run in which an outside path is named proves nothing and does not belong here.

### 11.3 Other conformance

There is nothing else to conform to. A host, installer, or package manager conforms by producing and maintaining app roots of [§1](#s1), and by honouring the mutability rules of [§4](#s4). How it does that is its own business.

## Appendix A — Reference path modules

These are examples, not normative. They implement [§3](#s3), [§4](#s4), and the modes of [§1.3](#s1.3).

### Python

```python
import os
import pathlib


def app_root() -> pathlib.Path:
    if r := os.environ.get("APP_ROOT"):
        root = pathlib.Path(r).resolve()
        if not (root / "app.toml").is_file():
            raise RuntimeError(f"APP_ROOT={r} holds no app.toml")
        return root
    # This module lives under contents/, so walk up to the directory holding app.toml.
    d = pathlib.Path(__file__).resolve().parent
    while not (d / "app.toml").is_file():
        if d.parent == d:
            raise RuntimeError(f"no app.toml above {__file__}")
        d = d.parent
    return d


def contents_dir() -> pathlib.Path:
    return app_root() / "contents"


def _dir(env: str, default: str) -> pathlib.Path:
    d = pathlib.Path(os.environ.get(env) or (app_root() / default))
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def run_dir() -> pathlib.Path: return _dir("APP_RUN_DIR", "run")
def data_dir() -> pathlib.Path: return _dir("APP_DATA_DIR", "data")
def cache_dir() -> pathlib.Path: return _dir("APP_CACHE_DIR", "cache")
```

### Rust

```rust
use std::os::unix::fs::DirBuilderExt;
use std::path::PathBuf;

pub fn app_root() -> PathBuf {
    if let Some(r) = std::env::var_os("APP_ROOT").filter(|r| !r.is_empty()) {
        let root = std::fs::canonicalize(&r).unwrap_or_else(|e| panic!("APP_ROOT={:?}: {e}", r));
        assert!(root.join("app.toml").is_file(), "APP_ROOT={:?} holds no app.toml", r);
        return root;
    }
    // Walk up from the real executable to the directory holding app.toml.
    let mut d = std::env::current_exe()
        .expect("current_exe")
        .canonicalize()
        .expect("canonicalize exe")
        .parent()
        .expect("exe has no parent")
        .to_path_buf();
    while !d.join("app.toml").is_file() {
        d = d.parent().expect("no app.toml above the executable").to_path_buf();
    }
    d
}

pub fn contents_dir() -> PathBuf {
    app_root().join("contents")
}

fn dir(env: &str, default: &str) -> PathBuf {
    let d = std::env::var_os(env)
        .filter(|v| !v.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| app_root().join(default));
    let _ = std::fs::DirBuilder::new().recursive(true).mode(0o700).create(&d);
    d
}

pub fn run_dir() -> PathBuf { dir("APP_RUN_DIR", "run") }
pub fn data_dir() -> PathBuf { dir("APP_DATA_DIR", "data") }
pub fn cache_dir() -> PathBuf { dir("APP_CACHE_DIR", "cache") }
```

### Go

```go
package paths

import (
	"os"
	"path/filepath"
)

func appRoot() string {
	if r := os.Getenv("APP_ROOT"); r != "" {
		if _, err := os.Stat(r); err != nil {
			panic("APP_ROOT=" + r + ": " + err.Error())
		}
		root := real(r)
		if _, err := os.Stat(filepath.Join(root, "app.toml")); err != nil {
			panic("APP_ROOT=" + r + " holds no app.toml")
		}
		return root
	}
	// Walk up from the real executable to the directory holding app.toml.
	exe, err := os.Executable()
	if err != nil {
		panic(err)
	}
	d := filepath.Dir(real(exe))
	for {
		if _, err := os.Stat(filepath.Join(d, "app.toml")); err == nil {
			return d
		}
		parent := filepath.Dir(d)
		if parent == d {
			panic("no app.toml above " + exe)
		}
		d = parent
	}
}

// real resolves symlinks, as section 3 requires of every path it derives from.
func real(p string) string {
	r, err := filepath.EvalSymlinks(p)
	if err != nil {
		panic(err)
	}
	return r
}

func contentsDir() string { return filepath.Join(appRoot(), "contents") }

func dir(env, def string) string {
	d := os.Getenv(env)
	if d == "" {
		d = filepath.Join(appRoot(), def)
	}
	os.MkdirAll(d, 0o700)
	return d
}

func runDir() string   { return dir("APP_RUN_DIR", "run") }
func dataDir() string  { return dir("APP_DATA_DIR", "data") }
func cacheDir() string { return dir("APP_CACHE_DIR", "cache") }
```

## Appendix B — Bundle templates

### Python

Launcher at `contents/bin/notepad` (shipped as `scripts/launcher.sh`):

```sh
#!/bin/sh
set -eu

# Resolve through symlinks, then walk up to the directory holding app.toml.
# Only when APP_ROOT is unset: a harness that points it at a temporary root
# has already said where the root is.
if [ -z "${APP_ROOT:-}" ]; then
  dir=$(dirname "$(readlink -f "$0")")
  while [ ! -f "$dir/app.toml" ]; do
    [ "$dir" = "/" ] && { echo "no app.toml above $0" >&2; exit 1; }
    dir=$(dirname "$dir")
  done
  APP_ROOT=$dir
fi
tree="$APP_ROOT/contents"

export APP_ROOT
export PYTHONPATH="$tree/lib${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPYCACHEPREFIX="$APP_ROOT/cache/pyc"
mkdir -p "$APP_ROOT/cache"

exec python3 -m notepad "$@"
```

`PYTHONPYCACHEPREFIX` keeps bytecode out of `contents/` for a regular package; a directory without `__init__.py` is a namespace package and is still compiled in place, so give the package an `__init__.py`.

Makefile:

```make
ID := org.example.notepad

bundle:
	rm -rf build/$(ID)
	mkdir -p build/$(ID)/contents/bin build/$(ID)/contents/lib build/$(ID)/contents/resources
	cp -r src/notepad build/$(ID)/contents/lib/
	cp -r assets/. build/$(ID)/contents/resources/
	install -m 0755 scripts/launcher.sh build/$(ID)/contents/bin/notepad
	cp app.toml build/$(ID)/app.toml
	find build/$(ID)/contents -name __pycache__ -prune -exec rm -rf {} +

dev: bundle
	./scripts/run-dev.sh build/$(ID)
```

`run-dev.sh` builds a temporary root — the build's `app.toml`, `contents/` symlinked to the build tree, fresh mutable directories — and points `$APP_ROOT` at it. That override is what it is for: the tree is hollow, and resolving from the launcher's real path would land in the build output and write `cache/` into it.

```sh
#!/bin/sh
set -eu
build=$(readlink -f "$1")
tmp=$(mktemp -d)
ln -s "$build/contents" "$tmp/contents"
cp "$build/app.toml" "$tmp/app.toml"
mkdir -p -m 700 "$tmp/data" "$tmp/cache" "$tmp/run"
trap 'rm -rf "$tmp"' EXIT INT TERM
APP_ROOT="$tmp" exec "$build/contents/bin/notepad" "$@"
```

### Cargo (Makefile)

```make
ID := org.example.notepad

bundle:
	rm -rf build/$(ID)
	mkdir -p build/$(ID)/contents/bin build/$(ID)/contents/resources
	cp target/release/notepad build/$(ID)/contents/bin/
	cp -r assets/. build/$(ID)/contents/resources/
	cp app.toml build/$(ID)/app.toml

dev: bundle
	./scripts/run-dev.sh build/$(ID)
```

### npm (package.json)

```json
{
  "scripts": {
    "bundle": "ID=org.example.notepad; rm -rf build/$ID; mkdir -p build/$ID/contents/bin build/$ID/contents/resources && cp -r dist/* build/$ID/contents/bin/ && cp -r assets/* build/$ID/contents/resources/ && cp app.toml build/$ID/app.toml",
    "dev": "npm run bundle && ./scripts/run-dev.sh build/org.example.notepad"
  }
}
```

## Appendix C — Glossary {#appc}

The words this specification uses in a particular sense, alphabetically. Each entry points at the section that defines it.

::: table
| Term | Meaning |
| --- | --- |
| **App root** | The one directory that is an app: `app.toml`, `contents/`, and whichever mutable directories exist ([§1](#s1)). Copy to install, delete to uninstall. |
| **Baked prefix** | An absolute install path written into a file inside `contents/`. Non-conforming, because the tree must stay relocatable ([§1.2](#s1.2)). |
| **Bundle** | An app root as distributed — `contents/` and its manifest — before an installer places it. |
| **`cache/`** | Regenerable mutable directory. Deletable at any time without losing user data ([§4](#s4)). |
| **Confinement** | Writing nothing outside the mutable directories and the paths the user names ([§1.4](#s1.4)). |
| **`contents/`** | The immutable tree that ships. It exists, it is never written at runtime, and it holds the entrypoint ([§1.2](#s1.2)). |
| **`data/`** | Durable mutable directory. Survives upgrades and machine restarts, and is removed only on purge ([§4](#s4)). |
| **Entrypoint** | The manifest field naming an executable inside `contents/`, run in the foreground ([§2.2](#s2.2)). |
| **Exposure** | The symlink or wrapper in a `PATH` directory through which an installed `entrypoint` is invoked ([§6.1](#s6.1)). |
| **Host** | Software that lists, launches, or draws integration from installed roots: a launcher menu, a file manager, a listing tool. Not the installer ([§11.3](#s11.3)). |
| **`id`** | Lowercase, dot-separated identifier. It names the app root, is stable across versions, and is self-asserted rather than verified ([§2.3](#s2.3)). |
| **Installer** | Software that produces a conforming app root and exposes its `entrypoint`. It accepts any source layout ([§6](#s6)). |
| **Launcher** | The script an interpreted app ships at `entrypoint`. It finds the root, prepares the runtime, and `exec`s the interpreter ([§5.1](#s5.1)). |
| **Manifest** | `app.toml`. TOML at the app root, describing the root. Its paths are relative to `contents/` ([§2](#s2)). |
| **Mutable directory** | One of `data/`, `cache/`, and `run/`: the only places the app writes on its own initiative ([§4](#s4)). |
| **Purge** | An uninstall that also removes `data/`. A plain uninstall keeps it ([§8](#s8)). |
| **Relocated mutable directory** | A mutable directory moved outside the app root by a supervisor, through the variable that names it ([§3.1](#s3.1)). |
| **Root override** | `$APP_ROOT`. It names the app root directly. An override, not a requirement: only needed when the tree being run is not a real one ([§3.2](#s3.2)). |
| **`run/`** | Session-scoped mutable directory, cleared or ignored on every startup ([§4](#s4)). |
| **Schema marker** | `data/version`. The app's own data-format version, compared at startup. Unrelated to the manifest's `version` ([§7.3](#s7.3)). |
| **Scope** | Per-user or system. An installation decision, and not recorded in the manifest ([§1.1](#s1.1)). |
| **Self-contained** | Dependencies resolved at build time and shipped inside `contents/`, with nothing fetched at startup ([§1.2](#s1.2)). |
| **Swap** | Replacing `contents/` and `app.toml` as a unit, so that `contents/` is never a mixture of two trees ([§7.1](#s7.1)). |
| **Uninstall** | Removing an installation: its exposure, `contents/`, `cache/`, `run/`, and `app.toml`. `data/` goes only on purge ([§8](#s8)). |
| **User-named path** | A path the user supplies at runtime. It is written as given, and is outside the reach of confinement ([§1.4](#s1.4)). |
| **`version`** | The manifest field holding the build's version string. Display metadata only, never a compatibility signal ([§2.5](#s2.5)). |
:::

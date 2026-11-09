# ScanStation

Turn a Raspberry Pi 4 and a ScanSnap S1300i into a duplex scanner. Use the hardware button, an SSH command, or a local application. Choose a PDF per sheet, one per batch, or a single PDF across multiple feeder loads. The receipt profile crops narrow thermal paper and checks for mirrored print showing through on the back.

## Install or update

Use Debian 13 with Git, current APT indexes and a working SANE installation for the S1300i, including its firmware. Run as the user who will scan, with sudo access for installation. Confirm that this account can see the scanner with `scanimage -L`.

```sh
(set -e; d=$(mktemp -d); trap 'rm -rf "$d"' EXIT; git clone -q --depth 1 https://github.com/matnoublanche/ScanStation.git "$d"; sh "$d/install.sh")
scanstation --version
```

From a checkout, run `sh install.sh`. The installer installs Debian packages, updates the command in `/usr/local/bin` and starts `scanstation-button.service` under the scanning account at boot. Local settings and previous scans survive updates. Publish changes to GitHub before running the installer on the Pi.

## Scan from SSH

```sh
scanstation batch
scanstation sheet
scanstation page
scanstation multipass
scanstation batch --profile receipt
scanstation batch --no-filter --quality 85
scanstation batch --profile receipt --replay /path/to/original-pass
scanstation multipass --replay /path/to/first-pass --replay /path/to/next-pass
```

**Batch** combines retained sides into one PDF. **Page** produces a separately named single-page PDF for every retained side, including a printed back. **Sheet** creates a PDF for each physical sheet with at least one retained side. **Multipass** joins successive feeder loads. In an interactive shell, press Enter to add a load or type `f` to finish.

Each job has its own directory. Original PNM images are kept for every side, even those excluded from the PDF. Replay accepts consecutive `page-N.pnm` files beginning at 1, with an even number of sides. `pages.json` records per-side decisions. Final PDFs appear together in `pdf/` when assembly finishes. An entirely blank batch produces an empty PDF list.

The document profile acquires color at 300 dpi, deskews, crops feeder edges, filters blank sides, detects orientation, cleans the background with Leptonica, chooses grayscale or color, and exports 200 dpi JPEGs with img2pdf. The receipt profile exports grayscale at 300 dpi. It compares the back with a registered mirror of the front before discarding show-through. Use `--no-filter` to retain both sides, including faint notes. The SANE driver determines the maximum receipt length. Output is local. Paperless can perform document OCR downstream.

## Physical button and touchscreen API

```sh
scanstation select receipt --start-if-loaded --json
scanstation select multipass
scanstation start --json
scanstation status --json
scanstation next
scanstation finish
```

A touchscreen can call `select MODE --start-if-loaded` with `page`, `sheet`, `batch`, `multipass` or `receipt`. An empty feeder saves the choice for later. With paper loaded, the command starts the job immediately. Plain `select MODE` only saves the choice. Pressing the hardware button or running `start` uses the saved mode. The initial selection is batch. During a multipass wait, reload the feeder and press the button or use `next`. Use `finish` to assemble the PDF. The service accepts the next start as soon as capture has been queued. Press and release the scanner button; epjitsu refreshes sensor status roughly once per second.

Controller commands return a snapshot. Poll `status --json` for progress. Its fields include `mode`, `status` (ready, scan, waiting, finalizing or busy), `loaded` (null when unavailable), `sensor_error`, `progress` and `last`. Selection survives service restarts. Completed processing results survive service restarts. Direct SSH scanning is synchronous and does not change the selected mode.

## Configuration

Set defaults in `~/.config/scanstation/config.toml` or select another file with `--config PATH`. Command options take priority.

| Setting | Command option | Meaning |
|---|---|---|
| device | --device | SANE device identifier, or auto for a single epjitsu device |
| output | --output | Job directory, default ~/scanstation-jobs |
| filter | --filter / --no-filter | Remove blank sides by default |
| quality | --quality | JPEG quality from 1 to 95, default 76 |
| profile | --profile | document (default) or receipt |
| reference | --reference | Optional reference directory |

Run `scanstation verify --reference PATH` to check four reference images named `page-001.pnm` through `page-004.pnm`. The expected retained sides are 001, 003 and 004. If a reference directory is configured, filtered jobs check it before processing. Physical acquisition starts immediately and the originals survive a failed reference check.

## Engine events

Pass `--json` to a direct scan for UTF-8 newline-delimited JSON on stdout. Read stderr separately for driver diagnostics. Events include `reference`, `job` (directory), `pass` (number), `side` (pass_number, number, kept), `waiting` (choices), `completed` (pdf, report, sides, kept_count) and `error` (message). In a direct physical multipass job, write `next\n` or `finish\n` to stdin when waiting. Replays use all supplied pass directories automatically. A successful job exits with 0, a job error with 1 and invalid arguments with 2.

## Upgrading from 0.3

Version 0.4 uses English commands, options, JSON fields, events and report keys. Update external clients together with the Pi. The installer replaces the previous button service. Existing configuration keys and saved mode names are read automatically. The output location configured on an existing installation is preserved. Historical reports retain their original keys.

## Names and progress (0.5)

With `auto_name = true` (default), ScanStation reads the header of the first retained page of each PDF. It selects a confident heading, uses a unique recognized date (numeric day-month-year or French month name) from that header when available, and otherwise uses the local job date. A missing heading falls back to Scan. Duplicate filenames within a job get numeric suffixes. Set `--no-auto-name` for numbered filenames. This preview does not create an OCR layer. Receipt orientation can compare header readability in both directions when orientation detection is inconclusive.

For near-blank candidates with local contrast, confident text can veto removal. Graphics and codes still have independent image-based protection. Missing text alone never makes a side blank.

A `progress` event exposes the current stage (`verify_reference`, `captured`, `crop`, `filter`, `check_text`, `orient`, `clean`, `name`, `assemble`). Side numbers are per pass. An unknown total is null while feeding; the final PDF count is known during assembly. The controller exposes each processing job through `jobs` in `status --json`. The `completed` event means local PDFs are ready. Paperless delivery is a subsequent integration.

For a bright back with a narrow, continuous crease, the blank filter follows the
slope of the crease before testing for text. Readable text keeps the side.
Independent high-contrast marks, including small codes, can also keep it.

## Persistent processing queue (0.6)

The capture process holds the scanner for one feeder load (all requested passes
in multipass mode). It syncs the originals and commits the job and its scan
settings to SQLite before releasing the device. When status is ready, load the
next batch and press Scan, even while the previous batch is doing OCR.
Every batch has its own job ID, originals, page report and published PDF directory.

The separate systemd service `scanstation-worker.service` processes one job at a time,
in capture-completion order. Stopping or restarting it leaves queued work on disk.
An interrupted processing job starts again from its saved originals; already
published PDFs are acknowledged without publishing a second set. A capture
interrupted before handoff leaves its originals for inspection and is not processed
as a complete batch. Processing failures are recorded and later jobs continue.
Replay retained pass directories to retry a failed job.

`scanstation status --json` reports scanner availability separately from `jobs`.
Each entry includes its ID, state, timestamp and latest event. All outstanding jobs
and the last eight finished jobs are shown. The database is in
`~/.local/state/scanstation/jobs.sqlite3`. Direct CLI scans wait for their own result
by default; add `--enqueue` to return the job ID immediately after capture.

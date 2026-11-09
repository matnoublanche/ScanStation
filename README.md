# ScanStation

Turn a Raspberry Pi 4 and a ScanSnap S1300i into a standalone scanner for Paperless-ngx.

## Install or update

```sh
curl -fsSL https://raw.githubusercontent.com/matnoublanche/ScanStation/main/install | sh
```

Start with Raspberry Pi OS Lite **64-bit, Debian 13 (Trixie)**. Run the command as your regular scanning user with sudo access, from the Pi or over SSH. It downloads the project, installs the S1300i firmware and software dependencies, configures the 480 × 320 PiScreen and ADS7846 touchscreen, and enables the background services. Reboot once after the first installation. Run the same command for updates. Your settings and scan jobs are preserved.

For an installation without a display, run `export SCANSTATION_KIOSK=0` first.

## Scan a document

Select a mode, load the feeder and tap **Scan**. The physical scanner button uses the last selected mode, including after a restart.

| Mode | What you get |
| --- | --- |
| Page | One PDF per physical sheet. A printed front and back stay together. |
| Batch | One PDF for the entire feeder load, in scan order. |
| Multipass | One PDF across several feeder loads. Add the next stack when prompted, then choose **Finish PDF**. |
| Receipt | One PDF per receipt. Only the front is captured, cropped and saved in grayscale. |

The status light beside **Ready** shows scanner availability. The footer follows capture, cleanup, PDF assembly and Paperless delivery. Once capture finishes, you can load another batch while earlier documents are being processed or uploaded.

ScanStation straightens pages, cleans feeder edges and chooses color or grayscale. The blank-page filter checks faint text and isolated marks such as small codes before dropping a side. Filenames use the first retained page’s heading and date when available. Paperless handles searchable archive OCR.

## Connect Paperless

ScanStation saves PDFs locally by default. To enable delivery, edit `~/.config/scanstation/config.toml` as the scanning user:

```toml
paperless_url = "https://paperless.example.org"
paperless_inbox_tag = "inbox"
```

Save your API token in `~/.config/scanstation/paperless.token` with file permissions `600`. Use the name of an existing Paperless tag. New jobs enter a separate upload queue. A delivery is marked complete once ScanStation confirms both the import and the tag.

## Settings and recovery

The touchscreen starts in French. Set `ui_language = "en"` for English and restart `scanstation-kiosk.service`. The same configuration file controls the output directory, JPEG quality, blank-page filtering and automatic naming. See the [configuration example](config.example.toml).

Each job keeps its original images, page decisions and final PDFs under `~/scanstation-jobs/` by default. To rebuild a lost SD card, reinstall with the command above and restore your private `~/.config/scanstation/` backup, including the Paperless token. Back up the output directory separately to retain local scans, along with any custom reference images.

## Use from SSH

```sh
scanstation batch
scanstation status --json
scanstation batch --replay /path/to/saved/pass-001 --paperless-url ''
```

The last command rebuilds a saved batch locally. For all modes, controller commands, processing events and upload retries, see the [CLI reference](docs/cli.md). Version history and migration notes are in the [release notes](CHANGELOG.md).

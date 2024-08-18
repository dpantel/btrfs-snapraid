# BTRFS SnapRAID

This is a utility aimed at leveraging the power of [BTRFS](https://btrfs.readthedocs.io/en/latest/) to improve [SnapRAID](https://www.snapraid.it/) functionality.

## Why do this?

SnapRAID was designed to provide a very robust and flexible software "RAID" solution for **"infrequently changing files"**.

When files in the array change, this may create a "sync hole", that can lead to data loss.

If new files are [added](https://www.snapraid.it/faq#addandbreak) in between syncs, and a disk suffers a failure, these files will be lost.

If existing files are [deleted or modified](https://www.snapraid.it/faq#delandbreak) in between syncs, and a disk suffers a failure, this can lead to a much bigger problem, as any other data involved in the parity calculation with those files may be lost as well.

By leveraging the copy-on-write (COW) abilities of BTRFS to make "cheap copies" of the data files, this utility aims to plug this "sync hole".

## How does it work?

The key to shrinking the "sync hole" is preventing any file changes in the SnapRAID array until a sync is going to be performed.

This is accomplished by taking a snapshot of the "live" file system prior to each sync and letting SnapRAID create its content lists and parity calculations from that snapshot. That snapshot is kept in a frozen state until SnapRAID performs the next sync. If there is a disk failure before the next sync, SnapRAID has all of the information needed to recreate files in its array. Immediately prior to each sync, the SnapRAID snapshot is discarded and recreated from the "live" file system with all of the new changes. During the sync, SnapRAID incorporates those changes into its array.

A read-only snapshot of the SnapRAID data is created at the end of a successful sync. This is done to have a backup data-set, in case a disk fails _during_ a sync operation.

Note that any additions, updates, and deletions that happen in between syncs are still lost, just as they would be in a vanilla SnapRAID setup. However, those updates and deletions will no longer affect the parity calculation of other files, and so the damage is minimized.

## Wait, isn't there another script for this?

You are probably thinking of [snapraid-btrfs](https://github.com/automorphism88/snapraid-btrfs). It aims to solve the same problem, but in a different way. The biggest difference is that it relies on [Snapper](http://snapper.io/) under the hood to manage subvolumes and snapshots. This script uses native BTRFS commands and aims to be a bit more customizable with regards to file system setup and more transparent in its actions.

The other difference is that this script also incorporates a "maintenance mode", which can run a sequence of SnapRAID commands in order, utilizing BTRFS subvolumes/snapshots, where needed. This way, it can be added to a system schedule and run non-interactively. Basically, a built-in [snapraid-runner](https://github.com/Chronial/snapraid-runner).

# Installation & Setup

- [Installation](docs/INSTALL.md)
- [Setup](docs/SETUP.md)
- [Configuration Reference](docs/CONFIG.md)

# Usage

Most likely, you will add this to Cron or as a SystemD timer and run it in maintenance mode. But there are some helpful options for test-running in the console.

```sh
usage: btrfs_snapraid.py [-h] [-c config.conf] [-n] [-q | -v] [touch|sync|diff|maintenance]

Adds BTRFS magic to SnapRAID, manipulating subvolumes and snapshots to plug the "sync hole".
Can be invoked to run a single SnapRAID command (Touch, Diff, or Sync), or as a scheduled maintenance script, running Touch/Diff/Sync/Scrub in order.

positional arguments:
  touch|sync|diff|maintenance
                        SnapRAID action to perform on the array.
                        Defaults to "maintenance", if left blank.

options:
  -h, --help            show this help message and exit
  -c config.conf, --config config.conf
                        A configuration file is required.
                        If not specified, will look in
                        "./btrfs_snapraid.conf",
                        "/usr/local/etc/btrfs_snapraid.conf",
                        and "/etc/btrfs_snapraid.conf" in that order.
  -n, --dry-run         Do not make any changes.
                        Automatically sets verbosity to "-vv".
                        (Add "-vvv" to see debug messages.)
  -q, --quiet           Override the logging level(s) set in the config.
                        Suppresses all messages except errors.
  -v, --verbose         Override the logging level(s) set in the config.
                        Use "-v" for info, "-vv" for output,
                        and "-vvv" for debug messages.
```

# SnapRAID Commands

Only the SnapRAID commands that interact with, or are affected by, the special file system setup are implemented in this script. They will behave differently than `snapraid <command>`.

## Touch

`snapraid touch` will update the timestamps on the SnapRAID subvolumes. The command will succeed, but these changes will be overwritten the next time you run a Sync with this script, and cause a mismatch between files and SnapRAID contents. This is not harmful, but will cause a touch/update loop on the same set of files.

`btrfs_snapraid.py touch` will update the timestamps on the live-data subvolume, so these changes will be propagated the next time a Sync is run with this script.

## Diff

`snapraid diff` will always show "0" file changes, because the SnapRAID data is "frozen" until a Sync is to be performed.

`btrfs_snapraid.py diff` will look at the live-data subvolumes to report the actual changes since the last sync.

## Sync

`snapraid sync` will not do anything, because the SnapRAID data is "frozen" and there have been no changes since the last Sync.

`btrfs_snapraid.py sync` will recreate the SnapRAID subvolumes from the live-data subvolumes before running Sync and then save a "last known good state" snapshot of the SnapRAID subvolume.

## Maintenance

If no SnapRAID command is specified (or explicitly specified with `btrfs_snapraid.py maintenance`), the script will perform a set of actions in sequence, based on the settings in the configuration file.

1. Run `touch` on the live data, unless disabled in the config.
1. Refresh SnapRAID subvolumes with changes in the live-data subvolumes.
1. Run `diff` on the updated SnapRAID data
1. Run `sync` on the SnapRAID data, if the number of removed or updated files are below the configured thresholds, or the thresholds are disabled. If the thresholds are enabled and are exceeded, the script will exit _without running_ `sync`.
   - A manual `snapraid sync` will need to be run.
     - Note that you do not need to run `btrfs_snapraid.py sync` because the SnapRAID subvolumes have already been updated.
1. If `sync` was successful, save a read-only snapshot of the current SnapRAID subvolume. Rotate out older snapshots, if multiples are configured.
1. Run `scrub`, if configured.

## Fix

Currently not implemented by BTRFS SnapRAID.

Running `snapraid fix` will recover the files _on the SnapRAID subvolumes_.

These files must be be manually copied over to the live-data subvolumes before the next `btrfs_snapraid.py sync`, or they will be overwritten with the "bad" copies.

## Status / Scrub / Check / List / Dup / Rehash / Pool

These commands can be run directly with `snapraid <command>`.

## Devices / Smart / Up / Down

None of the commands dealing directly with disks will work as intended, if at all.

_They should not be attempted_.

# Disclaimers

This is a Python-learning exercise for me. I do not know what I am doing. This script makes big file system changes. Make backups prior to using. Use at your own risk.

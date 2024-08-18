# BTRFS-SnapRAID Configuration Options

It is important that the values provided in the configuration file, especially when dealing with directory paths, match the paths used in the SnapRAID confirugation file, as well as the mount points used by the OS (via `/etc/fstab` or similar).

The only restrictions on path and subvolume/snapshot names are that they use acceptable characters for the filesystem. So, "@subvolume" is perfectly fine. So is ".directory".

Also, wherever a path is requested, it is best to provide an absolute path.

## [mounts]

This section deals with the actual data drives and their mount points. All of the drive mount points need to share a common parent directory. If separate SnapRAID subvolume mount points are used (see below), they must also share a common parent directory.

### btrfs_mount_dir

Common parent directory for the data drive mount points.

### drives

A comma-separated list of btrfs-formatted data drive names. The absolute path of the mount point for each drive is derived from the `btrfs_mount_dir` and `drives` option. Remember to mount each drive's top-level/btrfs-root subvolume.

```ini
# config
btrfs_mount_dir = /btrfs
drives = data1, data2
```

```sh
# mount path of the btrfs-root of the first disk
/btrfs/data1
# mount path of the btrfs-root of the second disk
/btrfs/data2
```

```sh
# fstab entry
<disk1>   /btrfs/data1   btrfs   subvolid=5,...
```

### (optional) snapraid_mount_dir

Common parent directory for the separate SnapRaid subvolume mount points.

```ini
# config
snapraid_mount_dir = /snapraid
```

```sh
# mount path of the snapraid subvolume on the first disk
/snapraid/data1

# snapraid.conf
data d1 /snapraid/data1

# fstab
<disk1>   /snapraid/data1   btrfs   subvol=snapraid,...
```

Note the snapraid mount point names must match the drive mount point names.

Also note that if these secondary mounts are used, then this script will need to re-mount them during each run.

## [subvolumes]

This section deals with the names of the various subvolumes on each data drive. Note that the names must be consistent drive-to-drive.

### live_data

This is the name of the main data subvolume on each data, It is used for all non-SnapRAID read-write activities. (i.e. if you use mergerfs, these are the subvolumes you add to its config.)

These subvolumes reside in the btrfs-root of each disk.

```ini
# config
live_data = live
```

```sh
# path to the live-data subvolume on disk 1
/btrfs/data1/live
```

### snapraid_data

This is the name of the subvolume created by taking a snapshot of the live-data subvolume that is used for all (most) SnapRAID-related actions.

This subvolume should be used in the SnapRAID config for the 'data' location on each disk, unless using a separate snapraid mount.

```ini
# config
snapraid_data = snapraid
```

```sh
# snapraid.conf
data d1 /btrfs/data1/snapraid
```

This snapshot will be re-generated from the live-data subvolume prior to each SnapRAID sync.

In between syncs, this subvolume will remain untouched to maintain a stable 'frozen' state for SnapRAID recovery actions.

### (optional) snapraid_subdir

You can specify a sub-directory to store the SnapRAID subvolume and snapshots. This directory should reside in the btrfs-root of each disk, alongside the live-data subvolume.

If not specified, SnapRAID subvolumes/snapshots live in the btrfs-root.

```ini
# config
snapraid_subdir = snaps
```

```sh
# path to SnapRAID subvolume on disk 1
/btrfs/data1/snaps/snapraid

# Not using separate SnapRAID mount points...
# snapraid.conf
data d1 /btrfs/data1/snaps/snapraid

# Using separate SnapRAID mount points...
# fstab
<disk1>   /snapraid/data1   btrfs   subvol=snaps/snapraid,...
```

### (optional) snapraid_snaps_to_keep

As part of the process, a read-only snapshot of the SnapRAID subvolume will be saved at the successful completion of a SnapRAID Sync. It is meant to preserve the "last known valid state" of the SnapRAID data, in case something happens during the next SnapRAID sync.

At least one snapshot will be saved.

If you want to preserve more than one, you can specify the number here. This may be useful as an extra failsafe in case you delete a file, for example, and then allow SnapRAID to sync that change, and then realize you really needed that file. Well, if you keep a couple of extra snapshots, you may be able to find that file in the previous ones.

Realize that the number relates to the number of times this script is run. If the number is 5, and you run the script daily, then you have 5 days worth of backups. If you run the script every 10 minutes, you have just under an hour's worth of backups.

Also realize that if you have many and/or large file changes between snapshots, this option can quickly eat into your disk space.

## [snapraid]

### cmd

Absolute path to the SnapRAID executable.

### config

Absolute path to the SnapRAID configuration file.

## [snapraid_maintenance]

When you run this script without specifying a SnapRAID command, it will run in "maintenance mode", performing several actions in sequence. The options below control those actions.

### (optional) delete_threshold

The threshold number of DELETED files above which a sync will NOT take place.

Default = threshold disabled

### (optional) update_threshold

The threshold number of UPDATED files above which a sync will NOT take place.

Default = threshold disabled

### (optional) touch

Do you want to run a SnapRAID 'touch' command every time?

Default: yes

### (optional) scrub_plan

Do you want to run the SnapRAID 'scrub' command every time?

Plan corresponds to SnapRAID `--plan` scrub option:

    bad = Scrub blocks marked bad.
    new = Scrub just synced blocks not yet scrubbed.
    full = Scrub everything.
    0-100 - Scrub the exact percentage of blocks.

Default: disabled

### (optional) scrub_age

This corresponds to SnapRAID `--older-than` scrub option.

    If you specify a percentage amount, you can also use the '--older-than' option to define how old the block should be [in days]. The oldest blocks are scrubbed first ensuring an optimal check.

Default: 10 days, if a numeric scrub_plan is specified.

## [logging]

### (optional) console_level

What amount of messages do you want to see in the console?

- DEBUG = most verbose
- OUTPUT = very verbose, including details from SnapRAID and other parts of the script
- INFO = verbose; lists the tasks being performed
- WARNING = terse to quiet; only warnings
- ERROR = quiet; only errors

Default: WARNING

### (optional) file

Path to a log file to write to.

Default: disabled

### (optional) file_level

What amount of messages do you want to see in the log file?

Default: WARNING, if logging to file is enabled.

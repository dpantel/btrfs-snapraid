# Installation

## Requirements & Dependencies

- BTRFS filesystem on each data disk
  - The parity disk does not have this requirement
- `btrfs-progs` system package
- Python v3.8+
- Python [sh](https://github.com/amoffat/sh) module v2+
- [SnapRAID](https://www.snapraid.it)
- General knowledge of the Linux terminal, BTRFS and its commands, and SnapRAID and its commands

## Installing

1. Install dependencies
1. Copy `btrfs_snapraid.py` to a location of your choice, and make it executable.
1. Copy `btrfs_snapraid.conf.example` as `btrfs_snapraid.conf` to a location of your choice and edit it to match the setup above.
   - The script will automatically look for a configuration file in "./btrfs_snapraid.conf", "/usr/local/etc/btrfs_snapraid.conf", and "/etc/btrfs_snapraid.conf" in that order.

### Users & Permissions

Make sure that the user running this script has sufficient privileges to perform the following:

- Create, delete, and move BTRFS snapshots
- Run SnapRAID
- Run Python and have access to the SH module
  - This is especially important when using `pip` to install python dependencies
- Depending on configuration, mount and unmount devices
- Depending on configuration, write a log file

## Uninstalling

First and foremost, stop any scheduled runs of the script while you are making these changes. You should delete the script and its configuration file, if you don't plan on using it again.

If you want to stop using the script, but do not want to move your data, you just need to edit one configuration file.

- _Option A:_ If you created separate SnapRAID mounts, edit `/etc/fstab` and change the subvolume names _of the snapraid mounts_ to the "live-data" subvolume.
  - Ex: `<disk1>    /snapraid/data1  btrfs   ...,subvolume=live,...`
  - You do not need to change the SnapRAID config.
- _Option B:_ If you did not create separate mounts, then edit `/etc/snapraid.conf` and change the data disk paths to the "live-data" subvolume.
  - Ex: `data d1 /btrfs/data1/live/`
  - You do not need to change fstab.

If you want to fully reverse the setup, so that SnapRAID has access to the data disks, rather than subvolumes, you will have to move the data on each disk, in addition to editing configuration files.

- Move all of the contents of each _live-data subvolume_ into its disk's brtfs-root.
- Edit `/etc/snapraid.conf` and update each "data" entry.
- Edit `/etc/fstab` and remove SnapRAID mount entries, if they exist.

Finally

- **Run a SnapRAID diff** to make sure it can find everything and is not missing any files. It may complain of UUIDs changing, but the files should be ok.
- Run a SnapRAID sync.
- Delete unneeded subvolumes and snapshots at your leisure.

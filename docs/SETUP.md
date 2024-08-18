# Setup

## Disk Layout and Subvolumes

This utility requires some manual setup of the structure of your data disks.

1. Mount the "btrfs-root" or "top-level" subvolume (`subvol=/` or `subvolid=5`) of each data disk to a common and permanent location.
1. Create a "live-data" subvolume in the root of each data disk. This is where all of the non-SnapRAID read and write activities will take place.
   - If you already have data on the disk, move it all into this subvolume. Do not leave any SnapRAID-eligible files outside of it.
1. Create a (read-write) snapshot of the "live-data" subvolume for each data disk. This is the subvolume that SnapRAID will interact with. Optionally, you may create a subdirectory to hold this (and additional) snapshots.
1. Optionally, create another set of mount points for each of the SnapRAID subvolumes.
   - While SnapRAID will work when pointed to its subvolumes directly, it will see them as subdirectories and complain about a lack of UUIDs and being unable to use inodes for file-move detection.Using these secondary mounts tricks SnapRAID into seeing its subvolumes as disks.
   - Make sure that these mount points are also in a common and permanent location and have the same names as the storage drives that contain them.
1. Edit `/etc/fstab`
   - Add entries for the top-level subvolume mount points for each data disk, as in step #1.
   - (Optionally) If using separate SnapRAID mounts (step #4), add entries to mount each SnapRAID subvolume into its mount point.
1. Edit `/etc/snapraid.conf`
   - For each data drive, use either the path to the SnapRAID subvolume (step #3) or its mount point (step #4)
   - If you want to place extra SnapRAID content files on the data drives, they should go into the btrfs-root, not any of the subvolumes.

## BTRFS SnapRAID Configuration

Update `btrfs_snapraid.conf` to match the disk/subvolume settings above.

For detailed option explanations and examples, see [CONFIG.md](CONFIG.md)

## Sample Setup

This is a sample setup to make it obvious how everything ties together, using the defaults/examples from the config file.

_filesystem_

```sh
/btrfs/						# <-- common parent directory for data disk mount points
    data1/                  # <-- mount point for the btrfs top-level subvolume for disk1
        snapraid.content    # <-- content file in the btrfs-root of each disk
        live/               # <-- main data subvolume
        snaps/              # <-- optional snapraid subdirectory
            snapraid/       # <-- main snapraid subvolume
            snapraid.1/     # <-- read-only snapshot of the snapraid subvolume
    data2/
        snapraid.content
        live/
        snaps/
            snapraid/
            snapraid.1/


/snapraid/					# <-- common parent directory for the snapraid mount points
    data1/  				# <-- mount point for the 'snapraid' subvolume on disk1
    data2/
```

_/etc/fstab_

```sh
# storage BTRFS top-level subvolumes
<disk1>   /btrfs/data1   btrfs   subvolid=5,...
<disk2>   /btrfs/data2   btrfs   subvolid=5,...

# snapraid subvolume mounts
# note that snapraid mount names mirror btrfs mount names
<disk1>   /snapraid/data1   btrfs   subvolume=snaps/snapraid,...
<disk2>   /snapraid/data2   btrfs   subvolume=snaps/snapraid,...
```

_/etc/snapraid.conf_

```
content /btrfs/data1/snapraid.content
content /btrfs/data2/snapraid.content
...
data d1 /snapraid/data1/
data d2 /snapraid/data2/
```

_btrfs_snapraid.conf_

```bash
[mounts]
btrfs_mount_dir = /btrfs
drives = data1, data2
snapraid_mount_dir = /snapraid

[subvolumes]
live_data = live
snapraid_data = snapraid
snapraid_subdir = snaps
```

# A Note About Scrubbing

You can keep letting SnapRAID scrub the array, or you can scrub each filesystem with BTRFS instead. You don't need to do both.

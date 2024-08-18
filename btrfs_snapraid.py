#!/usr/bin/python3

"""Wrapper for SnapRAID to add BTRFS magic.

https://github.com/dpantel/btrfs-snapraid

Runs selected SnapRAID commands or a sequence of "maintenance" commands,
utilizing the power of BTRFS subvolumes and snapshots to shrink
SnapRAID's "sync hole".

See `btrfs_snapraid.py --help` for quick usage information.
See the Readme and other documentation for in-depth information.
"""


import argparse
import configparser
import logging
import os.path
import re
import sys
from collections import namedtuple
from logging.handlers import RotatingFileHandler
from typing import Any, Optional, Union
# Used for method type hinting ie: (var: Optional[str] = None)
# Can also just use Union and specify (var: Union[str, None] = None, ...).
# In v3.10, can be replaced by (var: str | None = None, ...)
from tempfile import NamedTemporaryFile
import sh


BS_NAME = __name__


class BSLogging:
    """Encapsulates and streamlines logging setup.

    Combines elements of logging.getLogger() with logging.basicConfig() and
    extends that functionality, via BSLogging.get_logger().
    """

    # Used for all handlers that do not have a level request
    _DEFAULT_LOG_LEVEL = logging.WARNING

    # Define a base log formatter
    _FORMATTER = logging.Formatter(
        fmt="%(asctime).19s | %(levelname)-8s | %(message)s")

    # Dictionary of handlers assigned to each logger.
    # Don't need a list of loggers, because that is maintained by
    # the logging Manager.
    _handlers = {}

    @classmethod
    def get_logger(cls, name: str, console_level_name: Optional[str] = None,
                   file_log: Optional[str] = None,
                   file_level_name: Optional[str] = None) -> logging.Logger:
        """Combines logging.getLogger() and logging.basicConfig() and more.

        Sets up or retrieves a Logger via logging.getLogger(_name_), and thus
        keeps maintains a single Logger object for each name.

        Sets up a StreamHanlder, which outputs to STDOUT at the requested level
        (or WARNING as a default). Sets up a RotatingFileHandler, if a file
        path is provided, at the requested level (or WARNING).

        Subsequent calls to this method with the same name will return the same
        Logger object, but with the levels updated to the passed arguments.

        The `file_log` argument is multi-functional. Once a file handler has
        been established, passing False will remove it, and passing a path
        will replace it with a new handler with the provided path.

        Returns the initialized logging.Logger object.
        """

        # Has this logger already been initialized?
        # (Can also use if `name not in logging.Logger.manager.loggerDict`)
        # (Can also check for existance of those levels directly in logging)
        if name not in cls._handlers:
            # Define custom logging levels and names to destinguish
            # events from this script vs from commands run from it (via SH).
            # Note that setting the custom levels to a real level number
            # will overwrite those level names. So use adjacent ints

            # Want output to be near INFO, but still below it and suppressible
            logging.OUTPUT = logging.INFO - 1
            logging.addLevelName(logging.OUTPUT, "OUTPUT")
            # Want output errors to show up if logging ERRORS, so make it +1
            logging.OUTERR = logging.ERROR + 1
            logging.addLevelName(logging.OUTERR, "OUTERR")

            # Init (or re-init) the logger
            logger = logging.getLogger(name)

            # Init a console log handler; use SDTOUT instead of STDERR
            console_handler = logging.StreamHandler(sys.stdout)
            # Set the default formatter
            console_handler.setFormatter(cls._FORMATTER)
            # Add handler to logger
            logger.addHandler(console_handler)
            # Add handler to class record
            cls._handlers[name] = {}
            cls._handlers[name]['console'] = console_handler
        else:
            # Re-init the logger
            logger = logging.getLogger(name)

        # Set or update console reportable level
        cls._set_handler_level(logger, cls._handlers[name]['console'],
                               console_level_name)

        # If a file handler is set up, but there is a request to remove it
        if 'file' in cls._handlers[name] and file_log is False:
            # Remove this handler from logger and class record
            logger.removeHandler(cls._handlers[name]['file'])
            del cls._handlers[name]['file']
        # If a file handler has been requested
        elif file_log:
            # A file handler already exists...
            # FileHandler does not have a way of checking the file path,
            # so just close and replace this handler.
            if 'file' in cls._handlers[name]:
                cls._handlers[name]['file'].close()
                del cls._handlers[name]['file']

            try:
                # Init a file handler
                file_handler = RotatingFileHandler(
                    file_log, encoding='utf8',
                    maxBytes=10*1024*1024, backupCount=9)

                # Set the default formatter
                file_handler.setFormatter(cls._FORMATTER)
                # Add handler to logger
                logger.addHandler(file_handler)
                # Add handler to class record
                cls._handlers[name]['file'] = file_handler
            except IOError as e:
                logger.warning('Unable to write log to "%s" -- %s.',
                               file_log, e)

        # If there is a file handler, set or update its level
        if 'file' in cls._handlers[name]:
            cls._set_handler_level(logger, cls._handlers[name]['file'],
                                   file_level_name)

        logger.debug('Logger established for "%s".', name)

        return logger

    @classmethod
    def _set_handler_level(cls, logger, handler, level_name: str) -> None:
        # Validate and filter level name
        level = cls._filter_log_level(level_name)

        # Set the handler level, but not below ERROR
        handler.setLevel(min(level, logging.ERROR))

        # Make sure that the logger level is at least as low as the handler.
        # Otherwise log records will get dropped before getting to the handler.
        if level < logger.getEffectiveLevel():
            logger.setLevel(level)

    @classmethod
    def _filter_log_level(cls, log_level_name: str) -> int:
        """Verifies that a given level name is a valid log level.

        If the given level name is one of the named log levels, returns
        the corresponding numeric logging level. Otherwise, defaults to
        the class default constant.
        """
        if isinstance(log_level_name, str):
            return getattr(logging, log_level_name.upper(),
                           cls._DEFAULT_LOG_LEVEL)

        return cls._DEFAULT_LOG_LEVEL


class BSConfig:
    """Class to load, parse, and validate configuration options.

    The resulting configuration can be accessed en-bloc as `.config`, or
    individually via `.get(section, +/-option)`.

    Initially fetched the configuration into a nested dictionary. However,
    now the resulting configuration is a namedtuple. This allows for attribute
    access of options (config.section.option vs config['section']['option']),
    which I find more convenient. This also makes the configuration immutable.
    Whether that is too limiting remains to be seen, but it makes sense at the
    moment to enforce the values as set, since this class goes through so much
    trouble making sure the provided values are correctly typed and valued in
    the first place.

    Other alternatives tried were a "DotDict" or "AttrDict" type of class,
    overloading the dictionary to allow attribute access of values. Then a
    SimpleNamespace object, which also allowed for attribute access and seemed
    less clunky. However neither enforced immutability. Finally attempted
    using dataclass structures, but despite being seemingly the perfect
    data type for the job, they did not add any benefit. If, in the future, it
    is apparent that a mutable config is of benefit, then can use dataclasses.
    """

    # All the possible configuration options, their types,
    # whether they are required, and optional defaults.
    _prop = namedtuple('_prop', ['required', 'type', 'default'],
                       defaults=(str, None))
    _config_schema = {
        'mounts': {
            'btrfs_mount_dir': _prop(True),
            'drives': _prop(True),
            'snapraid_mount_dir': _prop(False)
        },
        'subvolumes': {
            'live_data': _prop(True),
            'snapraid_data': _prop(True),
            'snapraid_subdir': _prop(False, default=''),
            'snapraid_snaps_to_keep': _prop(False, int, 1)
        },
        'snapraid': {
            'cmd': _prop(True),
            'config': _prop(True)
        },
        'snapraid_maintenance': {
            'delete_threshold': _prop(False, int),
            'update_threshold': _prop(False, int),
            'touch': _prop(False, bool, True),
            'scrub_plan': _prop(False),
            'scrub_age': _prop(False, int, 10)
        },
        'logging': {
            'console_level': _prop(False),
            'file': _prop(False),
            'file_level': _prop(False)
        }
    }

    # Default config file locations, if one is not specified.
    _config_file_search = [
        'btrfs_snapraid.conf',
        '/usr/local/etc/btrfs_snapraid.conf',
        '/etc/btrfs_snapraid.conf',
    ]

    @property
    def config(self):
        """The configuration data object."""
        return self._config

    def __init__(self, config: Optional[Union[str, os.PathLike, dict]] = None,
                 req_log_level: Optional[str] = None) -> None:
        self._logger = BSLogging.get_logger(BS_NAME, req_log_level)
        self._config = self._parse_config(self._load_config(config))

    def get(self, section: str, option: Optional[str] = None
            ) -> Union[namedtuple, Any]:
        """Returns the value of the option, or the section tuple."""
        sect = getattr(self._config, section)

        if option:
            return getattr(sect, option)

        return sect

    def _die(self, msg: str) -> None:
        """Prints an error message and exits with error."""
        self._logger.error(msg)
        sys.exit(1)

    def _load_config(self,
                     config: Optional[Union[str, os.PathLike, dict]] = None
                     ) -> configparser.ConfigParser:
        """Loads the config and returns the resulting ConfigParser.

        If config is a string or a path, tries to read in the file.
        If config is None, then tries to read in one of the default config file
        locations.

        If config is a dictionary, then reads in the values directly. This is
        provided mostly for testing.
        """
        # Init the parser
        parser = configparser.ConfigParser(interpolation=None)

        # Parsing a dictionary?
        if isinstance(config, dict):
            return parser.read_dict(config)

        # Allow a search of several "default" locations for the config file,
        # but only if one is not specified
        if not config:
            self._logger.debug('No config file specified...')
            # Find the first config file that actually exists
            for path in self._config_file_search:
                self._logger.debug('Looking for config in "%s"', path)
                if os.path.exists(path):
                    self._logger.debug('Found config in "%s"', path)
                    config = path
                    break

        # Still nothing...
        if not config:
            self._die('A configuration file is required. Either specify a path'
                      ' as an argument, or place a file in one of the default'
                      ' locations. (See --help for details)')

        # Try to read the config file
        try:
            with open(os.fspath(config), mode='r', encoding='utf8') as f:
                try:
                    parser.read_file(f)
                except configparser.ParsingError as e:
                    self._die(f'Problem parsing config file. {e}')
        except FileNotFoundError:
            if config:
                self._die(f'File not found: "{config}".')
        except IOError:
            self._die(f'Unable to read config from "{config}".')

        return parser

    def _parse_config(self, parser: configparser.ConfigParser) -> namedtuple:
        """Parses config options and returns a nested namedtuple.

        Validates that all required options are present, validates that all
        options have correct value types. Sets defaults for those options that
        have them.

        Note: If want to switch from namedtuple to dataclass for the config
        object, then replace `namedtuple()` calls with `make_dataclass()`.
        """
        # Option types correlated to parser getter function
        get_by_type = {
            str: parser.get,
            int: parser.getint,
            bool: parser.getboolean,
            float: parser.getfloat
        }

        # Create a namedtuple with the configuration sections
        config = namedtuple('config', self._config_schema.keys())

        # Temporary dictionary to hold completed section tuples
        sections = {}
        # Iterate through the schema, pulling in option values from the parser
        for sect, opts in self._config_schema.items():
            # Temporary dictionary to hold the validated values
            options = {}
            for opt, props in opts.items():
                # Grab the value of this option from the config parser.
                # Default to None if option doesn't exist, or is blank.
                # Use type-specific functions and exit with error on wrong type
                try:
                    val = get_by_type[props.type](sect, opt, fallback=None)
                    val = val if val != "" else None
                except (TypeError, ValueError):
                    bad_val = parser.get(sect, opt)
                    self._die(f'Config Error: Invalid value or type for option'
                              f' "{opt}" in section "[{sect}]". Expecting type'
                              f' ({props.type}), "{bad_val}" given.')

                # If this option is required, but has no value, exit with error
                if props.required and val is None:
                    self._die(f'Config Error: Option "{opt}" in section'
                              f' "[{sect}]" is required.')

                # Save the value or the default (which could still be None)
                val = val if val is not None else props.default

                # Do a couple of final value verifications

                # Snapraid_snaps_to_keep needs to be >= 1
                if (opt == 'snapraid_snaps_to_keep') and (val < 1):
                    self._logger.warning('Option "snapraid_snaps_to_keep" in'
                                         ' section [subvolumes] cannot be less'
                                         ' than 1. Setting option value = 1.')
                    val = 1

                # "drives" option may have multiples in a comma-separated
                # string. Split it into a list.
                if opt == 'drives':
                    val = [
                        d for d in (
                            d.strip() for d in
                            val.split(',')
                        )
                        if d
                    ]

                # Store the value in the options dict
                options[opt] = val

            # Create a namedtuple with all the options in this section
            section = namedtuple(sect, opts.keys())
            # Populate this section tuple with its options
            sections[sect] = section(**options)

        # Populate the config tuple with its sections
        result = config(**sections)

        self._logger.debug('Parsed configuration:\n%s',
                           __import__('pprint').pformat(result)
                           )

        return result


class BTRFSSnapRAID:
    """Wrapper for SnapRAID to add BTRFS magic"""

    def __init__(self, config_file: Optional[Union[str, os.PathLike]] = None,
                 dry_run: bool = False, req_log_level: Optional[str] = None
                 ) -> None:
        # This will be used throughout the whole class
        self._dry_run = dry_run

        # Parse the config
        self._config = BSConfig(config_file, req_log_level).config

        # Use the requested log level, if provided
        if req_log_level:
            console_log_level = file_log_level = req_log_level
        else:
            # Otherwise, use config file settings
            console_log_level = self._config.logging.console_level
            file_log_level = self._config.logging.file_level

        # Set up a logger
        self._logger = BSLogging().get_logger(BS_NAME, console_log_level,
                                              self._config.logging.file,
                                              file_log_level)

    def _die(self, msg: str) -> None:
        """Prints an error message and exits with error."""
        self._logger.error(msg)
        sys.exit(1)

    def _sh_err_msg(self, e: sh.ErrorReturnCode) -> str:
        """Extracts info from an sh Error and creates a message."""
        return f'Command failed: "{e.full_cmd}" (err=self.{e.exit_code})'

    def _sh_log_err(self, msg: str) -> None:
        """Wrapper for sh output to right-strip newlines"""
        # Logger automatically adds newlines,
        # so don't want them from command output
        self._logger.log(logging.OUTERR, msg.rstrip())

    def _sh_log_out(self, msg: str) -> None:
        """Wrapper for sh output to right-strip newlines"""
        # Logger automatically adds newlines,
        # so don't want them from command output
        self._logger.log(logging.OUTPUT, msg.rstrip())

    def _sh_command(self, cmd: str, *args, force_run: bool = False,
                    exception_action: str = 'ERROR',
                    **sh_kwargs) -> Union[str, sh.RunningCommand]:
        """Wrapper for the SH module.

        Logs the full command; info if self._dry_run is true, debug otherwise.
        Executes command if self._dry_run is false or force_run is true.

        By default redirects all output to logger and returns empty string.
        Can return command output, or sh.RunningCommand object,
        depending on sh_kwargs.

        By default, an error during SH command exits the script with an error.
        This can be modified by setting exception_action to DEBUG|INFO|WARNING,
        which will cause the error to be logged with that level and allow the
        script to continue running.
        """
        # Bake all the arguments into the command.
        # This makes it easier to show the full command for a dry-run.
        cmd = cmd.bake(*args)

        # Log the command to be run.
        if self._dry_run:
            self._logger.info('(DRY-RUN): "%s"', cmd)
        else:
            self._logger.debug('"%s"', cmd)

        # Default to redirecting all output and errors to logger.
        # Merge with requested kwargs (allowing out/err overrides).
        sh_default_kwargs = {'_out': self._sh_log_out,
                             '_err': self._sh_log_err}
        sh_kwargs = {**sh_default_kwargs, **sh_kwargs}

        # Run the command if dry_run is False, or force_run is True.
        if force_run or not self._dry_run:
            try:
                # The return is most-likely and empty string empty, since
                # redirecting output to log. But there may be output or
                # a return with certain kwargs, so pass it on.
                return cmd(**sh_kwargs)
            except sh.ErrorReturnCode as e:
                # What action should happen here?
                # If request matches one of the (selected) logging actions
                if exception_action in ('DEBUG', 'INFO', 'WARNING'):
                    exception_action = exception_action.lower()
                    self._logger.exception_action(self._sh_err_msg(e))
                else:
                    # Default to an error causing the script to exit.
                    self._die(self._sh_err_msg(e))

        # Return an empty string by default as a throwaway.
        return ''

    def snapraid_subvol_refresh(self) -> None:
        """Updates data in the snapraid subvolumes.

        Updates the snapraid subvolume from the live-data subvolume on each
        data disk, by deleting the snapraid subvolume and taking a snapshot
        of the live subvolume. The delete action is a "lazy"
        `btrfs subvolume delete` that does not for a data sync on disk.

        This is meant to be run prior to each SnapRAID Sync action.
        """
        # Loop through every disk
        for disk in self._config.mounts.drives:
            self._logger.info('Refreshing SnapRAID snapshot from the active'
                              ' subvolume for %s', disk)

            # Build some paths
            data_subvol = os.path.join(
                self._config.mounts.btrfs_mount_dir, disk,
                self._config.subvolumes.live_data)
            snapraid_subvol = os.path.join(
                self._config.mounts.btrfs_mount_dir, disk,
                self._config.subvolumes.snapraid_subdir,
                self._config.subvolumes.snapraid_data)

            # If using a separate mount for SnapRAID,
            # unmount the current subvolume.
            if self._config.mounts.snapraid_mount_dir is not None:
                # Build a path to this disk
                snapraid_mount = os.path.join(
                    self._config.mounts.snapraid_mount_dir, disk)

                self._logger.debug('Unmounting "%s".', snapraid_mount)
                _ = self._sh_command(sh.umount, snapraid_mount)

            # Delete current subvolume
            self._logger.debug('Deleting "%s" subvolume.', snapraid_subvol)
            _ = self._sh_command(sh.btrfs.subvolume.delete, snapraid_subvol)

            # Snapshot the "live" subvolume
            self._logger.debug('Making a snapshot "%s" form subvolume "%s".',
                               snapraid_subvol, data_subvol)
            self._sh_command(sh.btrfs.subvolume.snapshot,
                             data_subvol, snapraid_subvol)

            # If using separate mount for SnapRAID, re-mount the new subvolume
            if self._config.mounts.snapraid_mount_dir is not None:
                self._logger.debug('(Re)mounting "%s".', snapraid_mount)
                _ = self._sh_command(sh.mount, snapraid_mount)

    def snapraid_subvol_save(self) -> None:
        """Saves a read-only snapshot of the snapraid subvolume.

        Take a read-only snapshot of the snapraid subvolume to save its
        "last known good state". Optionally, preserve multiple snapshots.
        This is meant to be run after a successful SnapRAID Sync action.
        """
        # Loop through every disk
        for disk in self._config.mounts.drives:
            self._logger.info('Rotating saved snapshots and saving current'
                              ' SnapRAID snapshot for %s', disk)

            # Build a path
            snapraid_subvol = os.path.join(
                self._config.mounts.btrfs_mount_dir, disk,
                self._config.subvolumes.snapraid_subdir,
                self._config.subvolumes.snapraid_data)

            # Loop through all the saved snapshots, starting with the oldest
            snaps_to_keep = self._config.subvolumes.snapraid_snaps_to_keep
            for n in range(snaps_to_keep, 0, -1):
                # Build a path based on the subvolume path and number
                snap = os.path.join(snapraid_subvol + '.' + str(n))

                # Does this snapshot exist?
                if os.path.exists(snap):
                    # Is this the limit of how many to keep?
                    if n == snaps_to_keep:
                        # Delete it
                        self._logger.debug('Deleting snapshot "%s".', snap)
                        _ = self._sh_command(sh.btrfs.subvolume.delete, snap)
                    else:
                        # Rotate it to the next number.
                        # Add '-v' flag so the action generates output that can
                        # be logged at the same level as other commands.
                        self._logger.debug(
                            'Roating snapshot from "%s" to "%s".',
                            snap, snapraid_subvol + '.' + str(n+1))
                        _ = self._sh_command(sh.mv, '-v', snap,
                                             snapraid_subvol + '.' + str(n+1))
                # Else, keep going

            # All of the older snapshots should have been rotated
            # Take a read-only snapshot of the SnapRAID subvolume
            self._logger.debug(
                'Creating a read-only snapshot "%s" from subvolume'
                ' "%s".', snapraid_subvol + '.1', snapraid_subvol)
            _ = self._sh_command(sh.btrfs.subvolume.snapshot, '-r',
                                 snapraid_subvol, snapraid_subvol + '.1')

    def snapraid(self, cmd: str, *args, config: Optional[str] = None,
                 return_cmd: bool = False, **sh_kwargs) -> Union[str, tuple]:
        """Wrapper method to create and call the SnapRAID executable via SH.

        Optionally, instead of executing the command, can return a tuple
        containing the SH command object and a list of associated arguments.

        Allows passing kwargs to SH.
        """
        # Build a custom SH Command for snapraid
        try:
            snapraid = sh.Command(self._config.snapraid.cmd)
        except sh.CommandNotFound:
            self._die('Unable to run the SnapRAID'
                      f' "{self._config.snapraid.cmd}".'
                      ' Either it is not at that location, it is not'
                      ' executable, or you do not have permissions to run it.'
                      )

        # Build a list of snapraid args, including the requested args.
        args = [
            '--conf',
            config or self._config.snapraid.config,
            '--quiet',
            *args,
            cmd
        ]

        # Is there a request to return the command?
        if return_cmd:
            return (snapraid, args)

        # Else, run the command; return result
        self._logger.log(logging.OUTPUT, '- ' * 30)
        _ = self._sh_command(snapraid, *args, **sh_kwargs)
        self._logger.log(logging.OUTPUT, '- ' * 30)
        return _

    def snapraid_live_data_config(self) -> str:
        """Generates a temporary SnapRAID config file pointing to Live Data.

        Some commands in this btrfs-snapraid setup need the current live-data
        to work correctly (Touch, and Diff, when run by itself). Generating
        a temporary configuration file pointing to the live data makes this
        possible.

        This function reads in the configuration file and replaces definitions
        for data drives to point to the live-data subvolume on each disk,
        instead of the snapraid subvolume, or its mount point.

        Returns the path of the temporary file.
        """
        # Figure out the current snapraid data drive paths and
        # build a path with a regex placeholder for drive names.
        if self._config.mounts.snapraid_mount_dir:
            # Using a dedicated mount directory
            curr_path = os.path.join(
                self._config.mounts.snapraid_mount_dir, '(?P<drive>.+)')
        else:
            # Using the path to the subvolume in the btrfs root dir
            curr_path = os.path.join(
                self._config.mounts.btrfs_mount_dir, '(?P<drive>.+)',
                self._config.subvolumes.snapraid_subdir,
                self._config.subvolumes.snapraid_data)

        # Now build a reg-ex search pattern for this data drive path
        re_search = re.compile(
            r'[\t ]*data[\t ]+(?P<drive_name>[\w]+)[\t ]+' + curr_path)

        # Need to read the current config file and write a temporary one.
        # Need to pass the temp file to SnapRAID, so don't delete on close.
        # (In 3.10 can use `with (A() as a, B() as b)` syntax.)
        # (In 3.12 use option delete_on_close=False for NamedTemporaryFile.)
        try:
            with open(self._config.snapraid.config, encoding='utf8') as config:
                with NamedTemporaryFile(delete=False, mode='w',
                                        encoding='utf8') as tmp:
                    self._logger.debug(
                        'Creating a temporary SnapRaid config in "%s".',
                        tmp.name)

                    for line in config:
                        # Ignore empty and comment lines
                        if not (l := line.strip()) or l[0] == '#':
                            continue

                        # Otherwise, search for the <data> setting line
                        if match := re_search.match(line):
                            # Build a new path using the extracted drive name
                            new_path = os.path.join(
                                self._config.mounts.btrfs_mount_dir,
                                match['drive'],
                                self._config.subvolumes.live_data)

                            # Rewrite the line with the new path
                            line = (f"data {match['drive_name']} {new_path}"
                                    "\n")

                        # Write either a replaced <data> line
                        # or the unmached config setting line
                        self._logger.debug(
                            'Writing "%s" to the temporary config.',
                            line.rstrip())
                        tmp.write(line)
        except FileNotFoundError:
            self._logger.error('There was a problem creating a temporary'
                               ' configuration file.')
            self._die('SnapRaid configuration file not found @'
                      f' "{self._config.snapraid.config}".')
        except IOError as e:
            self._logger.error('There was a problem creating a temporary'
                               ' configuration file.')
            self._die(f'{e}"')

        tmp.close()
        return tmp.name

    def snapraid_touch(self) -> None:
        """Runs SnapRAID Touch command.

        To do this effectively, it must be done on the "live data" subvolumes.
        Uses a temporary snapraid configuration that points to the live data
        to run this command.
        """
        # Generate the temporary config pointing to the live-data subvolumes
        tmp_config = self.snapraid_live_data_config()

        # Run Touch on the live data
        self._logger.info('Starting SnapRAID Touch on the Live data...')
        _ = self.snapraid('touch', config=tmp_config)

        # Delete the tmp config file
        os.unlink(tmp_config)

    def snapraid_scrub(self) -> None:
        """Runs SnapRAID scrub command based on config file options."""
        if (scrub_plan := self._config.snapraid_maintenance.scrub_plan):
            self._logger.info('Starting SnapRAID Scrub...')
            try:
                # Percent scrub? (Test for int, without actually converting.)
                _ = int(scrub_plan)
                # Yes. Run % / age scrub.
                _ = self.snapraid(
                    'scrub', '--plan', scrub_plan, '--older-than',
                    str(self._config.snapraid_maintenance.scrub_age))
            except ValueError:
                # Plan must not be numeric
                _ = self.snapraid('scrub', '--plan', scrub_plan)

    def snapraid_diff(self, use_live_data: bool = False) -> dict:
        """Runs SnapRAID Diff command.

        Returns number of deleted and updated files. This info is used by the
        maintenance method to determine if a Sync can be performed.

        Optionally, can pass a temporary configuration file pointing to the
        live-data subvolumes (see snapraid_live_data_config()) to SnapRAID.
        This is useful when running the Diff command in isolation and not as
        part of a maintenance sequence. This will show current diff numbers
        without touching the SnapRAID subvolumes.

        Returns { 'removed': #, 'updated': # }
        """
        # Run this on live data?
        tmp_conf = self.snapraid_live_data_config() if use_live_data else None

        self._logger.info('Starting SnapRAID Diff...')

        # Need to parse the output of this command to figure out
        # 'removed' and 'updated' counts.
        # So add some sh kwargs to return output in addition to logging it.
        # Also accept return code=2, which just means Diff found changes.
        diff_out = self.snapraid('diff', config=tmp_conf,
                                 _tee=True, _ok_code=(0, 2))

        # Need to go through the output line-by-line and search for
        # a line like '  ##### removed' or '   ### updated' to get counts.
        search = re.compile(r'\s+(?P<count>\d+)\s+(?P<action>removed|updated)')
        result = {'removed': 0, 'updated': 0} if self._dry_run else {}
        # The summary is at the bottom, so go through the output in reverse.
        for line in reversed(diff_out.splitlines()):
            # Found the right line?
            if (match := re.match(search, line)):
                # Add the result to the dictionary
                result[match['action']] = int(match['count'])
                # If both results have been found, then can stop searching.
                if 'removed' in result and 'updated' in result:
                    break

        if tmp_conf:
            # Delete the tmp config file.
            os.unlink(tmp_conf)

        # Return the numbers of removed and updated files.
        return result

    def snapraid_sync(self) -> None:
        """Runs SnapRAID Sync command.

        Manipulates BTRFS subvolumes and snapshots to update SnapRAID files to
        the most current state before performing the sync.

        This is only meant to be invoked when running Sync in isolation, and
        not as part of the maintenance sequence.
        """
        # Refresh subvolumes prior to sync.
        self.snapraid_subvol_refresh()

        # Sync
        self._logger.info('Starting SnapRAID Sync...')
        _ = self.snapraid('sync')

        # Save successful snapshot
        self.snapraid_subvol_save()

    def run_maintenance(self) -> None:
        """Runs a sequence of SnapRAID commands for regular array maintenance.

        The sequence depends on configuration file options, but is some
        combination of Touch / Diff / Sync / Scrub.
        If Deleted- or Updated-files thresholds are specified and are exceeded,
        the script is aborted prior to Sync.
        """

        self._logger.info('BTRFS SnapRAID Maintenance')
        self._logger.info('= ' * 30)

        if self._config.snapraid_maintenance.touch:
            self.snapraid_touch()

        # Refresh snapraid subvolumes from live data prior to diff
        self.snapraid_subvol_refresh()

        # Run the diff on new data
        diff = self.snapraid_diff()

        # Have sync thresholds been suprassed?
        del_thresh = self._config.snapraid_maintenance.delete_threshold
        upd_thresh = self._config.snapraid_maintenance.update_threshold
        err_text = ('The number of {} files ({}) exceeds the configured'
                    ' threshold of {}. Aborting Sync & Scrub. Once you confirm'
                    ' that all of the changes are desired, you will need to'
                    ' run a manual `snapraid sync` on the array. WARNING:'
                    ' SnapRAID array is NOT SYNCED!')
        if del_thresh and (diff['removed'] > del_thresh):
            # Too many removed files
            self._die(err_text.format('deleted', diff['removed'], del_thresh))
        if upd_thresh and (diff['updated'] > upd_thresh):
            # Too many updated files
            self._die(err_text.format('updated', diff['updated'], upd_thresh))

        # If got here, then can sync
        self._logger.info('Starting SnapRAID Sync...')
        _ = self.snapraid('sync')

        # Save snapraid snapshots after successful sync
        self.snapraid_subvol_save()

        # Scrub
        self.snapraid_scrub()

        self._logger.info('= ' * 30)


def parse_args() -> argparse.ArgumentParser:
    """Parses command-line arguments"""

    parser = argparse.ArgumentParser(
        description="""Adds BTRFS magic to SnapRAID, manipulating subvolumes
        and snapshots to plug the "sync hole". Can be invoked to run a single
        SnapRAID command (Touch, Diff, or Sync), or as a scheduled maintenance
        script, running Touch/Diff/Sync/Scrub in order. (
        https://github.com/dpantel/btrfs-snapraid)"""
    )
    parser.add_argument(
        '-c', '--config', metavar='config.conf',
        help='A configuration file is required. If not specified, will look'
             ' in "./btrfs_snapraid.conf", "/usr/local/etc/btrfs_snapraid'
             '.conf", and "/etc/btrfs_snapraid.conf".'
    )
    parser.add_argument(
        '-n', '--dry-run', action='store_true',
        help='Do not make any changes. Automatically sets verbosity'
             ' to "-vv". (Add "-vvv" to see debug messages.)'
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        '-q', '--quiet', action='store_true',
        help='Override the logging level(s) set in the config.'
             ' Suppresses all messages except errors.')
    verbosity.add_argument(
        '-v', '--verbose', action='count', default=0,
        help='Override the logging level(s) set in the config. Use "-v"'
             ' for info, "-vv" for output, and "-vvv" for debug messages.')

    snapraid_actions = ['touch', 'sync', 'diff', 'maintenance']
    parser.add_argument(
        'action', nargs='?', default='maintenance',
        metavar='|'.join(snapraid_actions),
        choices=snapraid_actions,
        help='SnapRAID action to perform on the array.'
             ' Defaults to "%(default)s", if left blank.'
    )

    return parser.parse_args()


def main():
    """Entry point if called as an executable.
    Parses command-line arguments and sets a requested logger level,
    if that is part of the arguments."""

    # Parse command line arguments
    args = parse_args()

    # Decide on the logging level based on the arguments
    if args.dry_run:
        if args.verbose > 2:
            logging_level = 'DEBUG'
        else:
            logging_level = 'OUTPUT'
    elif args.quiet:
        logging_level = 'ERROR'
    elif args.verbose == 1:
        logging_level = 'INFO'
    elif args.verbose == 2:
        logging_level = 'OUTPUT'
    elif args.verbose > 2:
        logging_level = 'DEBUG'
    else:
        logging_level = None    # Use config settings or class defaults

    # Initiate the btrfs-snapraid object with given args
    bs = BTRFSSnapRAID(args.config, args.dry_run, logging_level)

    if args.action == 'touch':
        bs.snapraid_touch()
    elif args.action == 'sync':
        bs.snapraid_sync()
    elif args.action == 'diff':
        bs.snapraid_diff(True)
    else:
        # Run the maintenance
        bs.run_maintenance()

    return 0


if __name__ == '__main__':
    sys.exit(main())

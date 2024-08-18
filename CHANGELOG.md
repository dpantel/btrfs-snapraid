# Changelog

## v0.5 - 2024-08-18 - Initial public release

- Fix multiple bugs in `snapraid_diff()`, which always returned 0/0 for removed/updated.
- Re-write BSLogger class to improve statefulness of each named Logger class.
- Re-write BSConfig class and switch from DotDict to namedtuple for the final configuration object.
- Add extensive type hinting.
- Add more DocString documentation.

## v0.4 - 2024-08 - Unreleased

- Fix error in maintenance-`diff`, which ran on stale data and always returned (0, 0).
- Add standalone `diff` command that looks at live-data subvolumes.
- Add `DotDict` class to convert config from nested dictionary to a nested class.
  - `config.logging.console_level` seems cleaner than `config['logging']['console_level']`.
- Fix multiple arguments declared as Class args instead of Object args
- Slight code refactoring to fit into Python v3.8
- Add type hints for all function arguments and returns.
- Improve DocStrings documentation.
- Update and fill out documentation.

## v0.3 - 2024-08 - Unreleased

- Remove reliance on external "runner" script and add maintenance mode.
- A lot of code refactoring and cleanup.
- Added detailed README and other documentation.

## v0.2 - 2024-07 - Unreleased

- Refactor code into classes.
- Separate configuration into its own file.
- Outstanding Issue: `touch` does not work.

## v0.1 - 2024-07 - Unreleased

- Initial Release.
- Wrapper around snapraid-runner.
- Configuration as constant variables in the script itself.
- Outstanding Issue: `touch` does not work.

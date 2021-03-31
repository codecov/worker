# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed
- Removed safeguard protecting against small downtimes when `Upload` objects were not created yet

### Fixed

### Security

## [v4.5.10]

### Added
- Added `flag_management` field and subfields to user YAML
- Added support for PR billing licenses on enterprise cases

### Changed

### Deprecated

### Removed
- Retired Gitlab v3 specific support

### Fixed
- Fixed visibility timeout issues, that in some cases could have caused the same task to be rerun more than once.

### Security


[unreleased]: https://github.com/codecov/worker/compare/v4.5.9...HEAD
[v4.5.10]: https://github.com/codecov/worker/compare/v4.5.9...v4.5.10


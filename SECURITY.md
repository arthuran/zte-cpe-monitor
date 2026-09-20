# Security Policy

## Supported versions

Security fixes are applied to the latest release and the `main` branch.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |

## Security model

ZTE CPE Monitor is a local administration utility. It authenticates to a CPE using credentials supplied by the device owner or administrator and reads radio/status data from the device's local Web UI API.

The project intentionally follows these defaults:

- no authentication bypass
- no cloud service or telemetry
- dashboard bound to `127.0.0.1` only
- no plaintext password in the application config
- macOS credentials stored in Keychain
- Linux credentials stored through Secret Service when `secret-tool` is available
- if no supported secure credential store exists, the password is not persisted
- configuration files are created with owner-only permissions where supported

Many ZTE CPE firmwares expose their local administration interface over HTTP rather than HTTPS. The challenge-response login avoids sending the plaintext password as an HTTP form value, but HTTP still does not provide transport confidentiality or server authentication. Use the tool only on a trusted local network or through a trusted tunnel.

## Support bundles

The built-in `support-bundle` command is designed for public compatibility reports. It exports capability structure and non-secret device family/version metadata, not raw router status values. Review any diagnostic file before sharing it if your environment has additional privacy requirements.

## Reporting a vulnerability

Please do not publish credentials, cookies, device identifiers, private IP topology, or exploit details in a public issue.

Use GitHub private vulnerability reporting / Security Advisories for this repository when available. Include:

- affected version
- operating system
- device model and firmware family (redact unique identifiers)
- reproduction steps
- expected and observed behavior
- security impact

For non-sensitive bugs, use normal GitHub issues.

## Scope

Useful reports include credential exposure, unsafe dashboard exposure, command injection, path/config permission problems, authentication/session handling flaws, and vulnerabilities in supported adapter logic.

Device firmware vulnerabilities should be reported to the device vendor or carrier unless the issue is caused by this project.
